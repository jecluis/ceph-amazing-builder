#!/bin/bash

my_dir=$(realpath $(dirname $0))
root_dir=$(realpath ${my_dir}/..)

usage() {

  cat << EOF
usage: $0 COMMAND [options]

build <args...>         builds ceph
list-images             list available images
help                    this message

commands:

  build <vendor> <release> <src> <out> [ccache]
    Builds ceph <release> from <vendor>, using the sources found at <src>, and
    leaving the final, compiled, tree in <out>. If [ccache] is specified, use
    it as the build cache.

EOF
}


_check_img_exists() {
  vendor="$1"
  release="$2"

  if ! podman images --format "{{.Repository}}:{{.Tag}}" | \
      grep -q cab/run/${vendor}:${release} ; then
    return 1
  fi
  return 0
}

_list_images() {

  repo=

  IFS=$'\n'
  for i in $(podman images --format "{{.Repository}} {{.Tag}}" | \
              grep cab/run | \
              sed -n 's/.*run\/\([a-zA-Z]\+\) \(.*\)/\1 \2/p'); do
    repo=$(echo $i | cut -f1 -d' ')
    release=$(echo $i | cut -f2 -d' ')
    echo "repo: $repo, release: $release"
    # echo "n: ${#repo}, ${#release}"
  done

}


_do_build() {
  if [[ $# -lt 4 ]]; then
    echo "error: missing parameters";
    usage
    return 1
  fi
  vendor="$1"
  release="$2"
  src="$3"
  out="$4"
  ccache="$5"

  [[ -z "${vendor}" || -z "${release}" ]] && \
    echo "must specify vendor and release" && exit 1
  [[ -z "${src}" || -z "${out}" ]] && \
    echo "must specify source and output directories" && exit 1

  with_ccache=false
  [[ -n "${ccache}" ]] && with_ccache=true

  if ! _check_img_exists ${vendor} ${release} ; then
    echo "build run image for ${vendor}/${release} not found."
    echo "please run 'image-build.sh' to build it."
    exit 1
  fi

  [[ ! -d "${src}" ]] && echo "source directory at '${src}' not found" && exit 1
  [[ ! -d "${out}" ]] && echo "creating ${out}" && (mkdir -p ${out} || exit 1)

  if $with_ccache ; then
    [[ ! -d "${ccache}" ]] && \
      echo "ccache directory at '${ccache}' not found" && exit 1
  fi

  if [[ ! -e "${src}/ceph.spec.in" ]]; then
    echo "source directory at '${src}' is not a ceph source tree"
    exit 1
  fi

  bin=${root_dir}/bin

  cat << EOF
run build with
      vendor: ${vendor}
     release: ${release}
  source dir: ${src}
  output dir: ${out}
  ccache dir: ${ccache}
     bin dir: ${bin}
EOF

  ccache_args=""
  if $with_ccache ; then
    volume_extra_args="-v ${ccache}:/build/ccache"
    run_extra_args="--with-ccache"
  fi

  podman run -it \
    --userns=keep-id \
    -v ${bin}:/build/bin \
    -v ${src}:/build/src \
    -v ${out}:/build/out \
    ${volume_extra_args} \
    cab/run/${vendor}:${release} \
    ${run_extra_args} || exit 1
}

case $1 in
  build)
    _do_build $2 $3 $4 $5 $6 || exit 1
    exit 0
    ;;
  list-images)
    _list_images || exit 1
    exit 0
    ;;
  help)
    usage ; exit 0
    ;;
  *)
    usage ; exit 1
    ;;
esac
