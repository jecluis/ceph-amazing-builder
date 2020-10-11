#!/bin/bash

do_with_ccache=false
do_fresh_build=false
do_with_debug=false
do_with_tests=false

while [[ $# -gt 0 ]]; do

  case $1 in
    --with-ccache) do_with_ccache=true ;;
    --fresh-build) do_fresh_build=true ;;
    --with-debug) do_with_debug=true ;;
    --with-tests) do_with_tests=true ;;
    *) echo "unknown argument '$1'" ; exit 1 ;;
  esac
  shift 1
done

cd /build/src


if $do_fresh_build ; then

  echo "=> cleaning up the git repository"
  git submodule foreach 'git clean -fdx' || exit 1
  git clean -fdx || exit 1

fi


extra_args="-DCMAKE_COLOR_MAKEFILE=OFF -DWITH_MGR_DASHBOARD_FRONTEND=ON"

if ! $do_with_tests ; then
  extra_args="$extra_args -DWITH_TESTS=OFF"
fi

if ! $do_with_debug ; then
  extra_args="$extra_args -DCMAKE_BUILD_TYPE=RelWithDebInfo"
fi

if $do_with_ccache ; then
  echo "---> WITH CCACHE <---"
  export CCACHE_DIR=/build/ccache
  export CCACHE_BASEDIR=/build/src
  extra_args="$extra_args -DWITH_CCACHE=ON" 
fi
export CEPH_EXTRA_CMAKE_ARGS="$extra_args"


# generate a builder spec file, adjusted for our purposes.
# this spec is slightly modified so we can build with ease, and parse
# informations out of it at later stages.
#
/build/bin/generate-builder-spec.sh || exit 1


git submodule sync || exit 1
git submodule update --init --recursive || exit 1


# parse build and install sections from our spec file.
# We will use the resulting scripts instead of running commands ourselves.
# This way we can ensure some sustainability across versions, as long as the
# resulting output is still compatible. *fingers crossed*
#
parse_spec=/build/bin/parse-spec-section.sh
${parse_spec} ceph.spec.builder build > /build/src/cab-make.sh

# there are a bunch of commands we need to perform after installing the sources,
# and those live in the specfile's install section. However, we don't want to
# install using the specfile's 'make' instruction -- we want to do that
# ourselves. As such, parse what we need, but drop the make instruction.
#
${parse_spec} ceph.spec.builder install |
  grep -v '.*make.*DESTDIR' > /build/out/post-make-install.sh

# perform the build stage
#
bash ./cab-make.sh || exit 1
rm ./cab-make.sh # we no longer need it

# move on to the install stage.
# This is customized, and based on the actual install stage described in the
# spec file. We need to do it manually so we can adjust where we're installing,
# and the target being installed. The spec file is not this flexible when it
# comes to installing.
#
pushd build || exit 1

nproc=$(nproc)
build_args=""
[[ -z "${nproc}" ]] && build_args="-j${nproc}"

install_type="install"
if ! $do_with_debug ; then
  install_type="install/strip"
fi

make ${build_args} DESTDIR=/build/out $install_type || exit 1

popd

# run all the post make install instructions. These will create needed files,
# set given permissions, and install some files onto specific locations.
#
bash /build/out/post-make-install.sh || exit 1
rm /build/out/post-make-install.sh

# Generate a set of instructions that we need to run after installing the files
# onto their final destination, in the final image. These would be run during
# the preinstall phase of package installation.
#
/build/bin/parse-spec-post-install.sh \
    /build/src/ceph.spec.builder > /build/out/post-install.sh
