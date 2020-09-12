#!/bin/bash


usage() {

  cat << EOF
usage: $0 <repo> <release> [--force]

Builds run image for repository <repo> and release <release>. If dependencies
do not exist, they will be built.

If '--force' is specified, then all dependencies will be built regardless of
existing.


allowed repos:
  ceph    upstream ceph repository at https://github.com/ceph/ceph.git
  suse    downstream ceph repository at https://github.com/suse/ceph.git

allowed releases per repository:
  ceph    master, pacific, octopus
  suse    master, ses7

(repositories and releases are not enforced, merely suggested)

EOF

}


_check_base_img_exists() {

  # we are lazy; we always assume the base img is leap-15.2
  if ! podman images --format "{{.Repository}}:{{.Tag}}" | \
       grep -q cacb/base:leap-15.2 ; then
    return 1
  fi
  return 0
}

_check_build_img_exists() {

  if ! podman images --format "{{.Repository}}:{{.Tag}}" | \
       grep -q cacb/build/$1:$2 ; then
    return 1
  fi
  return 0
}

_check_run_img_exists() {
  if ! podman images --format "{{.Repository}}:{{.Tag}}" | \
       grep -q cacb/run/$1:$2 ; then
    return 1
  fi
  return 0
}

_build_base_img() {
  echo "build base image"
  podman build -t cacb/base:leap-15.2 -f Dockerfile.base . || return 1
}


_build_base_build_img() {
  echo "build base build image for repo $1 release $2"
  podman build -t cacb/build/$1:$2 \
    --build-arg CEPH_RELEASE=$2 --build-arg CEPH_REPO=$1 \
    -f Dockerfile.base.build .
}


_build_run_img() {
  echo "build run image for repo $1 release $2"
  podman build -t cacb/run/$1:$2 \
    --build-arg CEPH_RELEASE=$2 --build-arg CEPH_REPO=$1 \
    -f Dockerfile.run .
}


[[ -z "$1" || -z "$2" ]] && usage && exit 1
[[ "$1" == "--help" || "$1" == "-h" ]] && usage && exit 0

repo="$1"
release="$2"

do_force=false
if [[ -n "$3" && "$3" == "--force" ]]; then
  do_force=true
fi


has_base_img=false
has_base_build_img=false

if ! _check_base_img_exists ; then
  _build_base_img || exit 1
elif $do_force ; then
  _build_base_img || exit 1
fi

if ! _check_build_img_exists $repo $release ; then
  _build_base_build_img $repo $release || exit 1
elif $do_force ; then
  _build_base_build_img $repo $release || exit 1
fi

if ! _check_run_img_exists $repo $release ; then
  _build_run_img $repo $release || exit 1
elif $do_force ; then
  _build_run_img $repo $release || exit 1
fi
