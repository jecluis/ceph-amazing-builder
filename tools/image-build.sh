#!/bin/bash

imgdir=$(realpath ./images)

usage() {

  cat << EOF
usage: $0 <vendor> <release> [--force]

Builds run image for repository <vendor> and release <release>. If dependencies
do not exist, they will be built.

If '--force' is specified, then all dependencies will be built regardless of
existing.


allowed vendors:
  ceph    upstream ceph repository at https://github.com/ceph/ceph.git
  suse    downstream ceph repository at https://github.com/suse/ceph.git

allowed releases per vendor:
  ceph    master, pacific, octopus
  suse    master, ses7

(repositories and releases are not enforced, merely suggested)

EOF

}


_check_base_img_exists() {

  # we are lazy; we always assume the base img is leap-15.2
  if ! podman images --format "{{.Repository}}:{{.Tag}}" | \
       grep -q cab/base/suse:leap-15.2 ; then
    return 1
  fi
  return 0
}

_check_base_release_img_exists() {
  if ! podman images --format "{{.Repository}}:{{.Tag}}" | \
       grep -q cab/base/release/$1:$2 ; then
    return 1
  fi
  return 0
}

_check_build_img_exists() {

  if ! podman images --format "{{.Repository}}:{{.Tag}}" | \
       grep -q cab/build/$1:$2 ; then
    return 1
  fi
  return 0
}

_build_base_img() {
  echo "build base image"
  podman build -t cab/base/suse:leap-15.2 \
    -f $imgdir/base/Dockerfile.base . || return 1
}

_build_release_img() {
  echo "build base release image for vendor $1 release $2"
  podman build -t cab/base/release/$1:$2 \
    --build-arg CEPH_RELEASE=$2 --build-arg CEPH_VENDOR=$1 \
    -f $imgdir/base/Dockerfile.release .
}

_build_base_build_img() {
  echo "build base build image for vendor $1 release $2"
  podman build -t cab/build/$1:$2 \
    --build-arg CEPH_RELEASE=$2 --build-arg CEPH_VENDOR=$1 \
    -f $imgdir/build/Dockerfile.build .
}


[[ -z "$1" || -z "$2" ]] && usage && exit 1
[[ "$1" == "--help" || "$1" == "-h" ]] && usage && exit 0

vendor="$1"
release="$2"

do_force=false
if [[ -n "$3" && "$3" == "--force" ]]; then
  do_force=true
fi

if ! _check_base_img_exists ; then
  _build_base_img || exit 1
elif $do_force ; then
  _build_base_img || exit 1
fi

if ! _check_base_release_img_exists $vendor $release ; then
  _build_release_img $vendor $release || exit 1
elif $do_force ; then
  _build_release_img $vendor $release || exit 1
fi

if ! _check_build_img_exists $vendor $release ; then
  _build_base_build_img $vendor $release || exit 1
elif $do_force ; then
  _build_base_build_img $vendor $release || exit 1
fi