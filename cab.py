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



config = Config()


@click.group()
def cli():
	# print(f"config path: {config._config_dir}")
	# print(f"has config? {config.has_config()}")
	pass


def _prompt_directory(prompt_text: str) -> str:
	path = None
	while True:
		pathstr = click.prompt(
			click.style(prompt_text, fg="cyan"),
			type=str, default=None)
		path = Path(pathstr).absolute()
		if not path.exists() or not path.is_dir():
			click.secho("error: path does not exist or is not a directory.",
			            fg="red")
			continue
		break
	return str(path)


@click.command()
def init():
	"""Initiate the required configuration to perform builds."""

	if config.has_config() and \
	   not click.confirm(
		   click.style("Configuration file already exists. Continue?",
		   			   fg="red")):
		return

	config_path = config.get_config_path()
	
	while True:
		builds_dir = _prompt_directory("builds directory")			
		if click.confirm(
			click.style("Use ccache to speed up builds?", fg="green"),
			default=True):
			ccache_dir = _prompt_directory("ccache directory")			

		tlen = max(len(builds_dir), len(ccache_dir), len(config_path))+18
		t = "-"*tlen
		print(t)
		print(
f"""
     config path: {config_path}
builds directory: {builds_dir}
ccache directory: {ccache_dir}
""")
		print(t)
		if click.confirm(
			click.style("Is this okay?", fg="green"),
			default=True):
			break

	config.set_ccache_dir(ccache_dir)
	config.set_builds_dir(builds_dir)
	config.commit()
	print("configuration saved.")



@click.command()
@click.argument('buildname', type=click.STRING)
@click.argument('vendor', type=click.STRING)
@click.argument('release', type=click.STRING)
@click.argument('sourcedir',
	type=click.Path(exists=True, file_okay=False,
	                writable=True, resolve_path=True))
def create(buildname: str, vendor: str, release: str, sourcedir: str):
	"""Create a new build; does not build.

	BUILDNAME is the name for the build.\n
	VENDOR is the vendor to be used for this build.\n
	RELEASE is the release to be used for this build.\n
	SOURCEDIR is the directory where sources for this build are expected.\n
	"""
	if config.build_exists(buildname):
		click.secho(f"build '{buildname}' already exists.", fg="red")
		sys.exit(errno.EEXIST)

	# check whether a build image for <vendor>:<release> exists

	img, img_id = Containers.find_release_base_image(vendor, release)
	if not img or not img_id:
		click.secho(
			f"error: unable to find base image for vendor {vendor}" \
			f" release {release}",
			fg="red")
		click.secho("please run image-build.sh")
		sys.exit(errno.ENOENT)

	# check whether sourcedir is a ceph repository
	sourcepath: Path = Path(sourcedir).resolve()
	if not sourcepath.exists() or not sourcepath.is_dir():
		click.secho(
			f"error: sourcedir expected to exist as a directory",
		    fg="red")
		sys.exit(errno.ENOTDIR)
	
	specfile = sourcepath.joinpath('ceph.spec.in')
	if not specfile.exists():
		click.secho(
			f"error: sourcedir is not a ceph git source tree",
			fg="red"
		)
		sys.exit(errno.EINVAL)
	
	build = Build.create(config, buildname, vendor, release, sourcedir)
	build.print()
	click.secho(f"created build '{buildname}'", fg="green")



@click.command()
@click.argument('buildname', type=click.STRING)
@click.option('-d', '--with-debug', default=False, is_flag=True,
	help="build with debug symbols (increases build size)")
@click.option('--with-tests', default=False, is_flag=True,
	help="build with tests (increases build size)")
@click.option('--with-fresh-build', default=False, is_flag=True,
	help="cleans the source repository before building")
@click.option('--nuke-build', default=False, is_flag=True,
	help="destroys the output build directory before building")
def build(
    buildname: str,
    nuke_build: bool,
    with_debug: bool,
    with_tests: bool,
	with_fresh_build: bool
):
	"""Starts a new build.

	Will run a new build for the sources specified by BUILDNAME, and will create
	an image, either original or incremental.

	BUILDNAME is the name of the build being built.

	Please note that some flags, such as '--with-debug' and '--with-tests' will
	only be effective when building for the first time. Should one change their
	minds after the first build, it is necessary to recreate a fresh state in
	the sources directory.
	"""
	if not config.build_exists(buildname):
		click.secho(f"error: build '{buildname}' does not exist.", fg="red")
		sys.exit(errno.ENOENT)

	if nuke_build:
		sure = click.confirm(
		    click.style(
		        "Are you sure you want to remove the install directory?",
		        fg="red"),
		    default=False
		)
		if not sure:
			sys.exit(1)

	if with_fresh_build:
		sure = click.confirm(
		    click.style(
		        "Are you sure you want to run a fresh build?",
			    fg="red"),
		    default=False
		)
		if not sure:
			sys.exit(1)

	Build.build(config, buildname, nuke_build=nuke_build,
	            with_debug=with_debug, with_tests=with_tests,
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
		click.secho(f"build '{buildname}' does not exist")
		sys.exit(errno.ENOENT)

	if not click.confirm(f"Are you sure you want to remove build '{buildname}?",
	                     default=False):
		sys.exit(0)

	remove_build = click.confirm(f"Do you want to remove the build directory?",
	                             default=False)
	remove_containers = click.confirm(f"Do you want to remove the containers?",
	                                  default=False)
	success: bool = \
		Build.destroy(config, buildname,
	              remove_build=remove_build,
	              remove_containers=remove_containers)

	if not success:
		click.secho(f"error destroying build '{buildname}'; aborted.", fg="red")
	else:
		click.secho(f"destroyed build '{buildname}'", fg="cyan")
	


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
		click.secho(f"build '{buildname}' does not exist.", fg="red")
		sys.exit(errno.ENOENT)
	
	images: List[ContainerImage] = Containers.find_build_images(buildname)
	if len(images) == 0:
		click.secho(f"no images for build '{buildname}'", fg="red")
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
		click.secho(f"build '{buildname}' does not exist.", fg="red")
		sys.exit(errno.ENOENT)

	if not Containers.run_shell(buildname):
		click.secho(f"unable to run shell for build '{buildname}'", fg="red")
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