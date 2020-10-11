#!/bin/bash

[[ ! -e "ceph.spec.in" ]] && \
  echo "error: not a ceph source root directory" && \
  exit 1

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
