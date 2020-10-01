#!/usr/bin/python3
import click
import json
import errno
import sys
import subprocess
import shlex
import shutil
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List

from builder.config import Config
from builder.build import Build
from builder.containers import ContainerImage, Containers
from builder.utils import print_table, \
	serror, sokay, swarn, sinfo, \
	pinfo, pokay, perror


config = Config()


@click.group()
def cli():
	# print(f"config path: {config._config_dir}")
	# print(f"has config? {config.has_config()}")
	pass


def _prompt_directory(prompt_text: str) -> str:
	path = None
	while True:
		pathstr = click.prompt(sinfo(prompt_text), type=str, default=None)
		path = Path(pathstr).absolute()
		if not path.exists() or not path.is_dir():
			perror("error: path does not exist or is not a directory.")
			continue
		break
	return str(path)


@click.command()
def init():
	"""Initiate the required configuration to perform builds."""

	if config.has_config() and \
	   not click.confirm(
		   serror("Configuration file already exists. Continue?")):
		return

	config_path = config.get_config_path()
	
	while True:
		installs_dir = _prompt_directory("installs directory")			
		if click.confirm(sokay("Use ccache to speed up builds?"),
			default=True):
			ccache_dir = _prompt_directory("ccache directory")			

		tbl = [
			("config path", config_path),
			("installs directory", installs_dir),
			("ccache directory", ccache_dir)
		]
		print_table(tbl, color="cyan")

		if click.confirm(sokay("Is this okay?"), default=True):
			break

	config.set_ccache_dir(ccache_dir)
	config.set_installs_dir(installs_dir)
	config.commit()
	pokay("configuration saved.")



@click.command()
@click.argument('buildname', type=click.STRING)
@click.argument('vendor', type=click.STRING)
@click.argument('release', type=click.STRING)
@click.argument('sourcedir',
	type=click.Path(file_okay=False,
	                writable=True, resolve_path=True))
@click.option('--with-debug', default=False, is_flag=True,
	help="will be built with debug symbols (increases build size).")
@click.option('--with-tests', default=False, is_flag=True,
	help="will be built with tests (increases build size).")
@click.option('--clone-from-repo', nargs=1, type=click.STRING,
	help="git repository to clone from, into SOURCEDIR.")
@click.option('--clone-from-branch', nargs=1, type=click.STRING,
	help="git branch to clone from.")
def create(buildname: str, vendor: str, release: str, sourcedir: str,
           with_debug: bool, with_tests: bool,
		   clone_from_repo: str = None, clone_from_branch: str = None):
	"""Create a new build; does not build.

	BUILDNAME is the name for the build.\n
	VENDOR is the vendor to be used for this build.\n
	RELEASE is the release to be used for this build.\n
	SOURCEDIR is the directory where sources for this build are expected.\n
	"""
	if config.build_exists(buildname):
		perror(f"build '{buildname}' already exists.")
		sys.exit(errno.EEXIST)

	# check whether a build image for <vendor>:<release> exists

	img, img_id = Containers.find_release_base_image(vendor, release)
	if not img or not img_id:
		perror(
			f"error: unable to find base image for vendor {vendor}" \
			f" release {release}")
		perror("please run image-build.sh")
		sys.exit(errno.ENOENT)

	sourcepath: Path = Path(sourcedir).resolve()

	if clone_from_repo is not None:
		if len(clone_from_repo) == 0:
			perror("error: valid git repository required.")
			sys.exit(errno.EINVAL)
		
		extra_opts = ""
		if clone_from_branch is not None:
			if len(clone_from_branch) == 0:
				perror("error: valid branch required.")
				sys.exit(errno.EINVAL)
			extra_opts += f"-b {clone_from_branch}"

		if sourcepath.exists():
			perror(f"error: SOURCEDIR exists at {sourcepath}.")
			perror("can't clone to an existing directory")
			sys.exit(errno.EEXIST)
		
		cmd = f"git clone {extra_opts} {clone_from_repo} {sourcedir}"
		proc = subprocess.run(shlex.split(cmd))
		if proc.returncode != 0:
			perror(f"error: unable to clone repository")
			sys.exit(proc.returncode)

	elif clone_from_branch is not None:
		perror("error: --clone-from-branch requires --clone-from-repo")
		sys.exit(errno.EINVAL)

	# check whether sourcedir is a ceph repository
	if not sourcepath.exists() or not sourcepath.is_dir():
		perror(f"error: sourcedir expected to exist as a directory")
		sys.exit(errno.ENOTDIR)
	
	specfile = sourcepath.joinpath('ceph.spec.in')
	if not specfile.exists():
		perror(f"error: sourcedir is not a ceph git source tree")
		sys.exit(errno.EINVAL)
	
	build = Build.create(config, buildname, vendor, release, sourcedir,
	                     with_debug=with_debug, with_tests=with_tests)
	build.print()
	pokay(f"created build '{buildname}'")



@click.command()
@click.argument('buildname', type=click.STRING)
@click.option('--with-fresh-build', default=False, is_flag=True,
	help="cleans the source repository before building")
@click.option('--nuke-install', default=False, is_flag=True,
	help="destroys the install directory before building")
def build(
    buildname: str,
    nuke_install: bool,
	with_fresh_build: bool
):
	"""Starts a new build.

	Will run a new build for the sources specified by BUILDNAME, and will create
	an image, either original or incremental.

	BUILDNAME is the name of the build being built.

	"""
	if not config.build_exists(buildname):
		perror(f"error: build '{buildname}' does not exist.")
		sys.exit(errno.ENOENT)

	if nuke_install:
		sure = click.confirm(
			swarn("Are you sure you want to remove the install directory?"),
		    default=False
		)
		if not sure:
			sys.exit(1)

	if with_fresh_build:
		sure = click.confirm(
		    swarn("Are you sure you want to run a fresh build?"),
		    default=False
		)
		if not sure:
			sys.exit(1)

	Build.build(config, buildname, nuke_install=nuke_install,
	            with_fresh_build=with_fresh_build)


@click.command()
@click.argument('buildname', type=click.STRING)
def destroy(buildname: str):
	"""Destroy an existing build.

	Will always remove the existing configuration for build BUILDNAME.
	Optionally, may also remove existing an existing build, and the build's
	containers.

	BUILDNAME is the name of the build to be destroyed.
	"""

	if not config.build_exists(buildname):
		pinfo(f"build '{buildname}' does not exist")
		sys.exit(errno.ENOENT)

	if not click.confirm(
	        swarn(f"Are you sure you want to remove build '{buildname}?"),
	        default=False):
		sys.exit(0)

	remove_build = click.confirm(
	    swarn(f"Do you want to remove the build directory?"),
	    default=False)
	remove_containers = click.confirm(
	    swarn(f"Do you want to remove the containers?"),
	    default=False)
	success: bool = \
		Build.destroy(config, buildname,
	              remove_install=remove_build,
	              remove_containers=remove_containers)

	if not success:
		perror(f"error destroying build '{buildname}'; aborted.")
	else:
		pinfo(f"destroyed build '{buildname}'")
	


@click.command()
@click.option('-v', '--verbose', default=False, is_flag=True)
def list_builds(verbose: bool):
	build_names: List[str] = config.get_builds()
	for buildname in build_names:
		build = Build(config, buildname)
		build.print(with_prefix=True, verbose=True)


@click.command()
@click.argument('buildname', type=click.STRING)
def list_build_images(buildname: str):
	if not config.build_exists(buildname):
		perror(f"build '{buildname}' does not exist.")
		sys.exit(errno.ENOENT)
	
	images: List[ContainerImage] = Containers.find_build_images(buildname)
	if len(images) == 0:
		perror(f"no images for build '{buildname}'")
		sys.exit(0)
	
	img: ContainerImage
	for img in images:
		img.print()


@click.command()
@click.argument('buildname', type=click.STRING)
def shell(buildname: str):
	"""Drop into shell of build's latest container.

	BUILDNAME is the name of the build for which we want a shell.
	"""
	if not config.build_exists(buildname):
		perror(f"build '{buildname}' does not exist.")
		sys.exit(errno.ENOENT)

	if not Containers.run_shell(buildname):
		perror(f"unable to run shell for build '{buildname}'")
		sys.exit(errno.EINVAL)


cli.add_command(init)
cli.add_command(create)
cli.add_command(build)
cli.add_command(destroy)
cli.add_command(list_builds)
cli.add_command(list_build_images)
cli.add_command(shell)


if __name__ == '__main__':
	cli()