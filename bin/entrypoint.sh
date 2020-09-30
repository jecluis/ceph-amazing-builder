#!/bin/bash

do_with_ccache=false
do_fresh_build=false
do_with_debug=false
do_with_tests=false

while [[ $# -gt 0 ]]; do

  case $1 in
    --with-ccache) do_with_ccache=true ;;
    --fresh-build) do_fresh_build=true ;;
    --with-debug) do_with_debug=true ;;
    --with-tests) do_with_tests=true ;;
    *) echo "unknown argument '$1'" ; exit 1 ;;
  esac
  shift 1
done

cd /build/src


if $do_fresh_build ; then

  echo "=> cleaning up the git repository"
  git submodule foreach 'git clean -fdx' || exit 1
  git clean -fdx || exit 1

fi


extra_args="-DCMAKE_COLOR_MAKEFILE=OFF"

if ! $do_with_tests ; then
  extra_args="$extra_args -DWITH_TESTS=OFF"
fi

if ! $do_with_debug ; then
  extra_args="$extra_args -DCMAKE_BUILD_TYPE=RelWithDebInfo"
fi

if $do_with_ccache ; then
  echo "---> WITH CCACHE <---"
  export CCACHE_DIR=/build/ccache
  export CCACHE_BASEDIR=/build/src
  extra_args="$extra_args -DWITH_CCACHE=ON" 
fi
export CEPH_EXTRA_CMAKE_ARGS="$extra_args"

version=$(git describe --long --match 'v*' | sed 's/^v//')
rpm_version=$(echo ${version} | cut -d'-' -f 1-1)
rpm_release=$(echo ${version} | cut -d'-' -f 2- | sed 's/-/./')

cat << EOF
ceph version: ${version}
 rpm version: ${rpm_version}
 rpm release: ${rpm_release}
EOF

# we do a bit of hacking on the spec file because we are not using it for its
# intended purpose, but for (potentially) incremental builds, and definitely not
# using the tarball.
cat ceph.spec.in |
  sed "s/@PROJECT_VERSION@/${rpm_version}/g" |
  sed "s/@RPM_RELEASE@/${rpm_release}/g" |
  sed "s/@TARBALL_BASENAME@/ceph-${version}/g" |
  sed "s/mkdir build/mkdir build || true/g" |
  sed "s/%fdupes %{buildroot}%{_prefix}//g" |
  sed 's/%{buildroot}/\/build\/out/g' > ceph.spec.builder || \
      exit 1

git submodule sync || exit 1
git submodule update --init --recursive || exit 1


parse_spec=/build/bin/parse-spec-section.sh

${parse_spec} ceph.spec.builder build > /build/src/cab-make.sh

${parse_spec} ceph.spec.builder install |
  grep -v '.*make.*DESTDIR' > /build/out/post-make-install.sh

bash ./cab-make.sh || exit 1
rm ./cab-make.sh # we no longer need it
pushd build || exit 1

nproc=$(nproc)
build_args=""
[[ -z "${nproc}" ]] && build_args="-j${nproc}"

install_type="install"
if ! $do_with_debug ; then
  install_type="install/strip"
fi

make ${build_args} DESTDIR=/build/out $install_type || exit 1

popd

bash /build/out/post-make-install.sh || exit 1
rm /build/out/post-make-install.sh
