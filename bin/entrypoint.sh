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
  sed 's/%install/%install\necho "==> INSTALL <=="/g' > ceph.spec.builder || exit 1

# sed -e 's/mkdir build/mkdir build || true/g' < ceph.spec.in >
# ceph.spec.builder || exit 1
git submodule sync || exit 1
git submodule update --init --recursive || exit 1


# this is needed because if we're installing into something that is not,
# literally, an empty mock root directory (e.g., but into a container mount),
# then we may have a symlink from /var/run to /run, which would end up being
# this container's /run instead of the target's /run. Thus we need to be
# creative.
outdir_moved_run=false
if [[ -L "/build/out/var/run" ]]; then
  mv /build/out/var/run /build/out/var/run.tmp
  ln -fs /build/out/run /build/out/var/run
  outdir_moved_run=true
fi

rpmbuild -bi \
  --nodeps --noprep --noclean --nocheck --noclean \
  --buildroot=/build/out \
  --verbose --build-in-place --short-circuit\
  ceph.spec.builder


if [[ -e "/build/bin/parse-spec.sh" ]]; then
  chmod +x /build/bin/parse-spec.sh
  /build/bin/parse-spec.sh ./ceph.spec.builder > /build/out/post-install.sh
fi


if [[ $? -ne 0 ]]; then
  journalctl --no-pager -n 500
fi

if $outdir_moved_run ; then
  rm /build/out/var/run
  mv /build/out/var/run.tmp /build/out/var/run
fi