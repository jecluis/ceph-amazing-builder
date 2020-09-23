#!/bin/bash


with_ccache=false
while [[ $# -gt 0 ]]; do

  case $1 in
    --with-ccache) with_ccache=true ;;
    *) echo "unknown argument '$1'" ; exit 1 ;;
  esac
  shift 1
done

cd /build/src

if $with_ccache ; then
  echo "---> WITH CCACHE <---"
  export CCACHE_DIR=/build/ccache
  export CCACHE_BASEDIR=/build/src
  export CEPH_EXTRA_CMAKE_ARGS="-DWITH_CCACHE=ON"
fi


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
  sed 's/%build/%build\necho "===> BUILD <==="/g' |
  sed 's/%install/%install\necho "==> INSTALL <=="/g' > ceph.spec.builder || \
      exit 1

  #   sed 's/make DESTDIR=/make "$CEPH_MFLAGS_JOBS" DESTDIR=/g'

# sed -e 's/mkdir build/mkdir build || true/g' < ceph.spec.in >
# ceph.spec.builder || exit 1
git submodule sync || exit 1
git submodule update --init --recursive || exit 1


parse_spec=/build/bin/parse-spec-section.sh

${parse_spec} ceph.spec.builder build > /build/src/cab-make.sh

# rpmspec --parse ceph.spec.builder |
${parse_spec} ceph.spec.builder install |
  sed -n 's/rpmbuild\/BUILDROOT\/ceph-15.2.4-903.g8d6fa42688.x86_64/out/gp' |
  grep -v '.*make.*DESTDIR' > /build/out/post-make-install.sh

# for debug purposes
# cp /build/out/post-make-install.sh /build/bin/

bash ./cab-make.sh || exit 1
cd build || exit 1
nproc=$(nproc)
build_args=""
[[ -z "${nproc}" ]] && build_args="-j${nproc}"
make ${build_args} DESTDIR=/build/out install || exit 1
cd ..

bash /build/out/post-make-install.sh || exit 1


if [[ -e "/build/bin/parse-spec.sh" ]]; then
  /build/bin/parse-spec-post-install.sh \
    /build/src/ceph.spec.builder > /build/out/build/post-install.sh
fi

# if [[ $? -ne 0 ]]; then
#   journalctl --no-pager -n 500
# fi