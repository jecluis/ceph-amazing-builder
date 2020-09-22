#!/bin/bash

[[ $# -lt 3 ]] && echo "usage: $0 <vendor> <release> <source>" && exit 1

vendor="$1"
release="$2"
source="$3"

buildah unshare ./build.sh ${vendor} ${release} ${source} --do-container