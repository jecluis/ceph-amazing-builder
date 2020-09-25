#!/bin/bash

# extrabuildah="--log-level debug --runroot /srv/extravg/misc/containers-tmp/joao --root /home/joao/.local/share/containers/storage"

extrabuildah=

config="./config.json" # make this configurable via cli

usage() {
  cat << EOF
usage: $0 <vendor> <release> <src> [OPTIONS]

OPTIONS:

  --buildname <NAME>  build as part of build <NAME>
  --config|-c <PATH>  path to config file
  --skip-build        don't build the sources (default: false)
  --skip-container    skip building a container (default: false)
  --help|-h           this message

EOF
}

_check_image_exists() {
  img="${1}"
  if ! podman $extrabuildah images --format "{{.Repository}}:{{.Tag}}" | \
       grep -n ${img} ; then
    return 1
  fi
  return 0
}

do_build_path=false
do_build_name=false
do_skip_build=false
do_skip_container=false

build_path=""
build_name=""
config_path="./config.json"

args=()

while [[ $# -gt 0 ]]; do
  case $1 in
    --buildname)
      do_build_name=true
      build_name=$2
      shift 1
      ;;
    --config|-c)
      config_path=$2
      shift 1
      ;;
    --skip-build) do_skip_build=true ;;
    --skip-container) do_skip_container=true ;;
    --help|-h) usage ; exit 0 ;;
    *) args=(${args[@]} $1) ;;
  esac
  shift 1
done

[[ ${#args} -lt 3 ]] && echo "error: missing arguments" && usage && exit 1
[[ -z "${config}" ]] && \
  echo "error: config file not specified" && usage && exit 1
[[ ! -e "${config}" ]] && echo "error: missing config file" && usage && exit 1

$do_build_name && [[ -z "${build_name}" ]] && \
  echo "error: build name not specified" && usage && exit 1


build_root=$(jq '.build_root' ${config} | sed -n 's/"//gp')
ccache_root=$(jq '.ccache_root' ${config} | sed -n 's/"//gp')

[[ -z "${build_root}" ]] && echo "build root not configured" && exit 1
[[ ! -d "${build_root}" ]] && echo "build root does not exist" && exit 1

with_ccache=false
[[ -n "${ccache_root}" ]] && with_ccache=true
[[ ! -d "${ccache_root}" ]] && \
  echo "ccache root directory does not exist" && exit 1


vendor="${args[0]}"
release="${args[1]}"
srcdir="${args[2]}"


final_base_img=""
if ! $do_skip_container ; then

  if $do_build_name ; then
    final_base_img="cab-builds/${build_name}:latest"
    if ! _check_image_exists ${final_base_img} ; then
      final_base_img="cab/base/release/${vendor}:${release}"
    fi
  else
    final_base_img="cab/base/release/${vendor}:${release}"
  fi

  if ! _check_image_exists ${final_base_img} ; then
    echo "unable to find base image ${final_base_img} for build container"
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
if ! $do_build_name ; then
  build_time=$(date --utc +"%Y-%m-%dT%H-%M-%SZ")
  build_name="${vendor}-${release}_${build_time}"
fi

# make all build names lower case
build_name=$(echo ${build_name} | tr '[:upper:]' '[:lower:]')

outdir="${build_root}/${build_name}"
[[ ! -d "${outdir}" ]] && ( mkdir ${outdir} || exit 1 )


ccache_dir=
if $with_ccache ; then
  ccache_dir="${ccache_root}/${vendor}/${release}"
  if [[ ! -d "${ccache_dir}" ]]; then
    mkdir -p ${ccache_dir} || exit 1
    CCACHE_DIR=${ccache_dir} ccache -M 10G
  fi
fi

if ! $do_skip_build ; then
  echo "==> BUILDING SOURCES"
  mydir=$(dirname $0)
  $mydir/tools/run-build.sh build \
    ${vendor} ${release} ${srcdir} ${outdir} ${ccache_dir} || exit 1
fi


if ! $do_skip_container; then

  ctr_build_time=$(date --utc +"%Y%m%dT%H%M%SZ")

  container=$(buildah $extrabuildah from ${final_base_img})
  mnt=$(buildah $extrabuildah mount ${container})

  cat << EOF
==> BUILDING CONTAINER
  + build name: ${build_name} 
  + base image: ${final_base_img}
  +  container: ${container}
  + mount path: ${mnt}
EOF

  if [[ -z "${mnt}" || ! -d "${mnt}" ]]; then
    echo "error mounting final container overlay filesystem"
    exit 1
  fi

  rsync --verbose --update \
    --recursive --links --perms --group --owner --times\
    ${outdir}/* ${mnt}/ || exit 1

  if [[ -e "${mnt}/post-install.sh" ]]; then
    buildah $extrabuildah run ${container} bash -x /post-install.sh || exit 1
    buildah $extrabuildah run ${container} rm -f /post-install.sh || true
  fi

  final_container_image="cab-builds/${build_name}:${ctr_build_time}"
  echo "final container image: ${final_container_image}"
  # final_container_image="cab-builds/${vendor}/${release}:${ctr_build_time}"
  buildah $extrabuildah unmount ${container} || exit 1
  buildah $extrabuildah commit ${container} ${final_container_image} || exit 1
  buildah tag ${final_container_image} "cab-builds/${build_name}:latest"

  echo "container image: ${final_container_image}"
fi

echo "--> DONE <--"
