#!/bin/bash

bindir=${BINDIR:-/build/bin}

[[ ! -e "${bindir}/generate-builder-spec.sh" ]] && \
  echo "error: can't find specfile generator script" && \
  exit 1

bash ${bindir}/generate-builder-spec.sh || exit 1

requirements=($(rpmspec --parse ceph.spec.builder |
  sed -n 's/^Requires:[ ]\+\([-_a-zA-Z0-9]\+\).*/\1/p' |
  sort | uniq |
  grep -v 'ceph\|rados\|rgw\|rbd'))

recommended=($(rpmspec --parse ceph.spec.builder |
  sed -n 's/^Recommends:[ ]\+\([-_a-zA-Z0-9]\+\).*/\1/p' |
  sort | uniq |
  grep -v 'ceph\|rados\|rgw\|rbd'))

if [[ -n "${DRYRUN}" ]]; then
  echo ${requirements[*]} ${recommended[*]}
else
  zypper install -y ${requirements[*]} ${recommended[*]}
fi