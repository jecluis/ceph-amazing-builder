ceph amazing builder
--------------------

We aim at creating ceph container images easily, fast, and without much
intervention from the developer, for development purposes. These are not meant
for production environments. Production images should be obtained from the
openbuild service.

*NOTE:* the vast majority of tests, which have been manual by the way, have
focused on ensuring we're able to build suse's ses7 github branch. Although not
expected, there may be kinks when building other branches.


What we do
===========

* build a source tree from a container, optionally using a shared ccache;
* install built binaries into a fake root on the host;
* rsync binaries to a new image;
* create a new build image, or an incremental image based on an existing image.


What we don't do
================

* be very smart.

In a nutshell, building Ceph from sources into a medium is expected to be
performed, essentially, through `make-dist` -- which may then be consumed by
rpmbuild using the spec file.

We don't run `make-dist`, even though we parse the spec file significantly to
automate some of our steps. We also don't rely on `rpmbuild` to build rpms, and
choose to build all from source.

One of the most time consuming steps of building rpms is the dependency
resolution -- we don't resolve dependencies, and pay the price for that too. We
are able to know some of the dependencies from the spec file's `Requires`
entries, but our experience tells us that is not enough; and we haven't been
smart enough to unravel this mystery. Because of that, we have chosen to base
our image on the build image, which has all the development dependencies and
ensures the vast majority of requirements are present; those that are not are
later on added based on the `Requires` entries.

Additionally, there are several artifact that get installed onto the image that
would otherwise not be installed. We are working to figure out proper ways to
prevent them from being added, ideally without hardcoding conditions, but at
time of writing that has not been achieved. A perfect example of this is the
dashboard's frontend source directory; this adds about 700MB worth of node
modules.

In the end, we end up with an incredibly bloated image, roughly twice the size
of a production, distribution released image; read, about 2GB vs 1GB.


Setup
=====

Quick and dirty setup:

```
	$ sudo zypper install podman buildah
	$ python3 -m venv venv
	$ source venv/bin/activate
	$ pip install -r requirements.txt
	$ ln -fs $(pwd)/cab.py venv/bin/cab
```


Usage Overview
===============

First thing, the global environment needs to be initiated. This means creating a
configuration file pointing to some relevant directories: `installs`, where each
builds' fake install roots will lie; and `ccache`, where we will have the root
for `vendor/release` compilation caches. While maintaining a compilation cache
is perfectly possible, in order to speed builds we suggest having one. We will
keep a compilation cache per `vendor/release` combination, so that multiple
builds from the same base repository/branch will be shared.

```
	$ cab init
   	Do you want 'init' to create the builder tree for you? [Y/n]: Y
	Builder tree directory: /srv/containers/builder
           config path: /home/joao/.config/cab/config.yaml
	installs directory: /srv/containers/builder/installs
  	  ccache directory: /srv/containers/builder/ccache
	Is this okay? [Y/n]: Y
	configuration saved.
```

Alternatively, one can opt to specify individual directories.


The next step is to create our first build. Note that creating a build does not
mean building it -- we are simply instructing the tool that we intend to create
container images with these parameters.

```
	$ cab create <name> <vendor> <release> <sourcedir> [options]
```

E.g.,

```
	$ cab create ses7 suse ses7 /srv/containers/builder/sources/suse-ses7
	- buildname: ses7
   		- vendor: suse
   		- release: ses7
   		- sources: /srv/containers/builder/sources/ses7
   		- install: /srv/containers/builder/installs/ses7
   		- build: 
    		- with debug: False
    		- with tests: False
	created build 'ses7'
```

Note the two build parameters at the bottom: `with debug` and `with tests`.
These are flags that can be passed on to the `create` command, and will instruct
the tool to build with debug symbols and/or tests; both will increase the build
size significantly. In our runs, building with both generates about 9GB worth
of binaries, and thus approximately 10GB image, while turning both off generates
approximately 350MB worth of binaries and ~1.2GB final image.

Additionally, `cab create` accepts `--clone-from-repo` and
`--clone-from-branch`. The latter can't be specified without the former, and the
combination of both will clone a repository, checking out a given branch, into
the provided source directory; specifying only the former will clone and
checkout the repository's default branch.


Finally, building the container image is achieved with `cab build <buildname>`.

*NOTE BEFORE:* running `tools/image-build.sh` is a prerequisite step for
building containers, given we need base images to build images on.

```
	$ cab build ses7
	==> building sources
	      vendor: suse
	     release: ses7
	sources path: /srv/containers/builder/sources/ses7
	install path: /srv/containers/builder/installs/ses7
	 ccache path: /srv/containers/builder/ccache/suse/ses7
	  with debug: False
	  with tests: False
	(...)
	==> building container
	from build path: /srv/containers/builder/installs/ses7
           based on: localhost/cab/base/release/suse:ses7
	built container: cab-builds/ses7:20201001T152805Z (1a6106f9880d) 1.4GiB
```


Internally, the script is essentially running the same steps one would run to
build ceph from source: running cmake, running make from the `build/` directory,
and, finally, running `make install`. The only difference is that we're doing
all this from within a container built for this specific purpose.

While from the container's perspective it is building sources from `/build/src`
and installing the binaries onto `/build/out`, using the ccache available in
`/build/ccache` (if any), from the host's point of view we're passing the
build's source directory as a volume, along with the install and ccache paths.

Once the sources are built and the binaries installed, we will then rely on
`buildah` to create a working container (i.e., a container image that is not yet
committed), mount its root on the host, and `rsync` all the binaries to their
final destinations, prior to finally committing the final image state.

Because installing ceph on a system is a bit more than just copying executables
from place A to place B, our tool does some magic under the covers.
Specifically, during the build phase we parse the spec file (`ceph.spec.in`) in
the git repository, and grab the portions that would usually be run by rpm's
preinstallation phase to create directories, users, and to assign certain
permissions to certain files and binaries.


*NOTE:* the final image is based on the image used for building, and all
dependencies are fulfilled with build dependencies. There may be missing
dependencies, but we have not found a _reasonable_ and _reliable_ way to install
all missing dependencies for one specific release. It turns out that parsing the
spec file for `Requires` is not enough, and installing and uninstalling the ceph
packages is not reliable enough to ensure the image's correctness.



rootless podman
================

We have been running, and developing, running podman rootless. Should you wish
to go down that route as well, and should you need to figure out how, we
recommend following podman's upstream tutorial at

	https://github.com/containers/podman/blob/master/docs/tutorials/rootless_tutorial.md

and to ensure subuid's and subgid's are added for the user. These can be added
to `/etc/subuid` and `/etc/subgid`; e.g.,

```
	$ cat /etc/subuid
	joao:100000:65536
	$ cat /etc/subgid
	joao:100000:65536
```

known issues
=============

* Removing containers may fail due to image being used: usually this is due to
buildah's working containers still being around.


* container/storage.conf paths need to be on btrfs, otherwise it's going to fail
miserably. Additionally, seems it might need quite a lot of space for the
humongous images.

