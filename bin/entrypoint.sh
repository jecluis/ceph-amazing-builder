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

cat ceph.spec.in |
  sed "s/@PROJECT_VERSION@/${rpm_version}/g" |
  sed "s/@RPM_RELEASE@/${rpm_release}/g" |
  sed "s/@TARBALL_BASENAME@/ceph-${version}/g" |
  sed "s/mkdir build/mkdir build || true/g" |
  sed "s/%fdupes %{buildroot}%{_prefix}//g" |
  sed 's/%build/%build\necho "===> BUILD <==="/g' |
  sed 's/%install/%install\necho "==> INSTALL <=="/g' > ceph.spec.builder || \
      exit 1

# sed -e 's/mkdir build/mkdir build || true/g' < ceph.spec.in >
# ceph.spec.builder || exit 1
git submodule sync || exit 1
git submodule update --init --recursive || exit 1


# note: we got to run this against a 'build' (or whatever) directory inside our
# build output directory because rpmbuild's build stage **really** wants to
# remove that directory first. We believe there is a way to force it not to, by
# editting macros, but we're definitely not going there now. Too hackish.

rpmbuild -bi \
  --nodeps --noprep --noclean --nocheck \
  --buildroot=/build/out/build \
  --verbose --build-in-place \
  ceph.spec.builder || exit 1


if [[ -e "/build/bin/parse-spec.sh" ]]; then
  chmod +x /build/bin/parse-spec.sh
  /build/bin/parse-spec.sh ./ceph.spec.builder > /build/out/build/post-install.sh
fi

if [[ $? -ne 0 ]]; then
  journalctl --no-pager -n 500
fi