#!/bin/bash

config="./config.json" # make this configurable via cli

usage() {
  echo "usage: $0 <vendor> <release> <src> [--do-container]"
}

if [[ ! -e "${config}" ]]; then
  echo "missing config file"
  exit 1
fi

build_root=$(jq '.build_root' ${config} | sed -n 's/"//gp')
ccache_root=$(jq '.ccache_root' ${config} | sed -n 's/"//gp')

[[ -z "${build_root}" ]] && echo "build root not configured" && exit 1
[[ ! -d "${build_root}" ]] && echo "build root does not exist" && exit 1

with_ccache=false
[[ -n "${ccache_root}" ]] && with_ccache=true
[[ ! -d "${ccache_root}" ]] && \
  echo "ccache root directory does not exist" && exit 1

if [[ $# -lt 3 ]]; then
  usage
  exit 1
fi

vendor="$1"
release="$2"
srcdir="$3"

do_container=false
[[ -n "$4" && "$4" == "--do-container" ]] && do_container=true

final_base_img=""
if $do_container ; then
  final_base_img="cab/base/release/${vendor}:${release}"
  if ! podman images --format "{{.Repository}}:{{.Tag}}" | \
       grep -n ${final_base_img} ; then
    echo "unable to find base image for final build container"
    echo "you must run 'image-build.sh' first."
    exit 1
  fi
fi


[[ -z "${vendor}" ]] && usage && exit 1
[[ -z "${release}" ]] && usage && exit 1
[[ -z "${srcdir}" ]] && usage && exit 1
[[ ! -d "${srcdir}" ]] && echo "source dir does not exit" && exit 1
[[ ! -e "${srcdir}/ceph.spec.in" ]] && \
  echo "source dir is not a ceph source tree" && exit 1

# prepare output directory
build_time=$(date --utc +"%Y-%m-%dT%H-%M-%SZ")
build_name="${vendor}-${release}_${build_time}"

outdir="${build_root}/${build_name}"
[[ -d "${outdir}" ]] && \
  echo "funny enough, build directory at '${outdir}' exists..." && exit 1
mkdir ${outdir} || exit 1


ccache_dir=
if $with_ccache ; then
  ccache_dir="${ccache_root}/${vendor}/${release}"
  if [[ ! -d "${ccache_dir}" ]]; then
    mkdir -p ${ccache_dir} || exit 1
    CCACHE_DIR=${ccache_dir} ccache -M 10G
  fi
fi

mydir=$(dirname $0)
$mydir/tools/run-build.sh build \
  ${vendor} ${release} ${srcdir} ${outdir} ${ccache_dir} || exit 1

if $do_container; then

  ctr_build_time=$(date --utc +"%Y%m%dT%H%M%SZ")

  container=$(buildah from ${final_base_img})
  mnt=$(buildah mount ${container})

  echo "building working container ${container}"
  echo "  mount path: ${mnt}"

  if [[ -z "${mnt}" || ! -d "${mnt}" ]]; then
    echo "error mounting final container overlay filesystem"
    exit 1
  fi

  rsync --verbose --update \
    --recursive --links --perms --group --owner --times\
    ${outdir}/* ${mnt}/ || exit 1
  
  chroot ${mnt} \
    env PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    /bin/bash -x /post-install.sh

  rm ${mnt}/post-install.sh
  final_container_image="cab-builds/${vendor}/${release}:${ctr_build_time}"

  buildah commit ${container} ${final_container_image}
  buildah unmount ${container}

  echo "container image: ${final_container_image}"
fi

echo "--> DONE <--"