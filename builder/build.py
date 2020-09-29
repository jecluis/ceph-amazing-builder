import click
import sys
import shlex
import subprocess
import shutil
import os
from pathlib import Path
from datetime import datetime as dt
from .config import Config, UnknownBuildError
from .containers import Containers, ContainerImage
from typing import Tuple


def cprint(prefix: str, suffix: str):
	print("{}: {}".format(click.style(prefix, fg="cyan"), suffix))


class NoAvailableImageError(Exception):
	pass


class BuildError(Exception):
	pass


class ContainerBuildError(Exception):
	pass


class Build:

	_config: Config = None
	_name: str = None
	_vendor: str = None
	_release: str = None
	_sources: str = None

	def __init__(self, config: Config, name: str):
		self._config = config
		self._name = name
		self._read_config()

	def _read_config(self):
		if not self._config.build_exists(self._name):
			raise UnknownBuildError(self._name)
		build_config = self._config.get_build_config(self._name)
		assert build_config is not None
		assert 'name' in build_config
		assert 'vendor' in build_config
		assert 'release' in build_config
		assert 'sources' in build_config
		assert self._name == build_config['name']
		self._vendor = build_config['vendor']
		self._release = build_config['release']
		self._sources = build_config['sources']

	@classmethod
	def create(cls, config, name, vendor, release, sources):
		conf_dict = {
			'name': name,
			'vendor': vendor,
			'release': release,
			'sources': sources
		}
		config.write_build_config(name, conf_dict)
		return Build(config, name)

	def get_build_dir(self) -> str:
		builds = self._config.get_builds_dir()
		return str(builds.joinpath(self._name))

	def get_sources_dir(self) -> str:
		return self._sources

	def print(self, with_prefix=False, verbose=False):
		lst = [
			("- ", "buildname:", self._name),
			("   - ", "vendor:", self._vendor),
			("   - ", "release:", self._release),
			("   - ", "sourcedir:", self._sources),
			("   - ", "build dir:", self.get_build_dir())
		]
		for p, k, v in lst:
			s = "{}{}".format((p if with_prefix else ""), k)			
			print("{} {}".format(click.style(s, fg="cyan"), v))
			if not verbose:
				break

	def _remove_build(self):
		builds_dir = self._config.get_builds_dir()
		buildpath = builds_dir.joinpath(self._name)
		if not buildpath.exists() or not buildpath.is_dir():
			return
		buildpath.rmdir()

	def _remove_containers(self):		
		pass

	def _destroy(self, remove_build=False, remove_containers=False):
		if remove_build:
			self._remove_build()
		if remove_containers:
			self._remove_containers()
		self._config.remove_build(self._name)

	@classmethod
	def destroy(cls, config: Config, name: str,
	            remove_build=False,
	            remove_containers=False):
		build = Build(config, name)
		build._destroy(remove_build, remove_containers)


	@classmethod
	def build(cls, config: Config, name: str, nuke_build=False):
		if not config.build_exists(name):
			raise UnknownBuildError(name)
		build = Build(config, name)

		# nuke an existing build directory; force rebuild from start.    
		if nuke_build:
			sources_dir: str = build.get_sources_dir()
			sources_path: Path = Path(sources_dir)
			assert sources_path.exists() and sources_path.is_dir()
			bin_build_path = sources_path.joinpath('build')
			if bin_build_path.exists():
				assert bin_build_path.is_dir()
				shutil.rmtree(bin_build_path)
	
		build._build()


	def _build(self, do_build=True, do_container=True):

		ccache_path: Path = None
		build_path: Path = None
		base_build_image: str = None

		# prepare ccache
		if self._config.has_ccache():
			ccache_path: Path =	self._config.get_ccache_dir().joinpath(
			                             f"{self._release}/{self._vendor}")
			if not ccache_path.exists():
				ccache_path.mkdir(parents=True, exist_ok=True)
				ccache_size = self._config.get_ccache_size()
				cmd = f'ccache -M {ccache_size}'
				subprocess.run(
					shlex.split(cmd),
					env={'CCACHE_DIR': str(ccache_path)}
				)
		
		# prepare output build directory
		build_path = self._config.get_builds_dir().joinpath(self._name)
		build_path.mkdir(exist_ok=True)

		# check whether a previous build image exists (i.e., we're going to be
		# an incremental build), or if we are the first (in which case we need
		# to build on a release image)
		base_build_image: str = Containers.get_build_name_latest(self._name)
		if not base_build_image:
			base_build_image, _ = Containers.find_release_base_image(
				self._vendor, self._release)
			if not base_build_image:
				# we have no images to base our image on.
				raise NoAvailableImageError("missing release image")

		cprint("ccache path", ccache_path)
		cprint(" build path", build_path)
		cprint(" base image", str(base_build_image))
		
		if do_build:
			if not self._perform_build(build_path, ccache_path):
				raise BuildError()

		if do_container:
			if not self._build_container(build_path, base_build_image):
				raise ContainerBuildError()


	def _perform_build(self, build_path: Path, ccache_path: Path) -> bool:
		""" Performs the actual, containerized build from specified sources.

			The build process is based on running a specific build container,
			based on a given release, against the build's sources, and finally
			installing the binaries into the build's build path.

			build_path is the location of the directory where our final build
			will live.

			ccache_path is the location for the vendor/release ccache.
		"""

		build_image = \
			Containers.find_base_build_image(self._vendor, self._release)
		if not build_image:
			raise BuildError("unable to find base build image")

		bindir = Path.cwd().joinpath("bin")

		cmd = f"podman run -it --userns=keep-id " \
			  f"-v {bindir}:/build/bin " \
			  f"-v {self._sources}:/build/src " \
			  f"-v {str(build_path)}:/build/out"
		
		if ccache_path is not None:
			cmd += f" -v {str(ccache_path)}:/build/ccache"

		# currently, the build image's entrypoint requires an argument to
		# perform a build using ccache.
		cmd += f" {build_image}"
		if ccache_path is not None:
			cmd += " --with-ccache"
		
		# cprint("build cmd", cmd)
		proc = subprocess.run(
		            shlex.split(cmd), stdout=sys.stdout, stderr=sys.stderr)
		if proc.returncode != 0:
			raise BuildError(os.strerror(proc.returncode))
		return True
		

	def _run_cmd(self, cmd: str) -> Tuple[int, str, str]:
		proc = subprocess.run(shlex.split(cmd),
		                      stdout=subprocess.PIPE,
							  stderr=subprocess.PIPE)
		stdout = proc.stdout.decode("utf-8")
		stderr = proc.stderr.decode("utf-8")
		return proc.returncode, stdout, stderr


	def _run_buildah(self, cmd: str) -> Tuple[int, str]:
		buildah_cmd = 'buildah unshare buildah {}'.format(cmd)		
		ret, stdout, stderr = self._run_cmd(buildah_cmd)
		if ret != 0:
			click.secho(
			    "error running buildah {}: {}".format(cmd, stderr), fg="red")
			return ret, stderr
		return ret, stdout


	def _build_container(self,
	                     build_path: Path,
						 base_image: str
	) -> bool:

		# create working container (this is where our binaries will end up at).
		#
		ret, result = self._run_buildah(f"from {base_image}")
		if ret != 0:
			raise ContainerBuildError(os.strerror(ret))
		working_container = result.splitlines()[0]
		if not working_container or len(working_container) == 0:
			raise ContainerBuildError("no working container id returned")

		# mount our working container, so we can transfer our binaries.
		ret, result = self._run_buildah(f"mount {working_container}")
		if ret != 0:
			raise ContainerBuildError(os.strerror(ret))
		path_str = result.splitlines()[0]		
		if not path_str or len(path_str) == 0:
			raise ContainerBuildError("no mount point returned")

		mnt_path = Path(path_str)
		if not mnt_path.exists():
			raise ContainerBuildError("mount path does not exist")
		assert mnt_path.is_dir()

		# transfer binaries.		
		cmd = f"rsync --info=stats --update --recursive --links --perms "\
			  f"--group --owner --times "\
			  f"{str(build_path)}/ {str(mnt_path)}"		
		ret, _, stderr = self._run_cmd(cmd)
		if ret != 0:
			raise ContainerBuildError("{}: {}".format(os.strerror(ret), stderr))

		# run post-install script
		#  if present, will set permissions, create users and directories, etc.
		post_install_path = mnt_path.joinpath('post-install.sh')
		if post_install_path.exists():
			cmd = f"run {working_container} bash -x /post-install.sh"
			ret, result = self._run_buildah(cmd)
			if ret != 0:
				raise ContainerBuildError(
				         "{}: {}".format(os.strerror(ret), result))
			post_install_path.unlink()

		# create final container image
		#  container images are named according to the build name, and tagged
		#  with the creation date/time, and eventually tagged as 'latest'.
		#
		container_date = dt.now().strftime("%Y%m%dT%H%M%SZ")
		container_image_name = Containers.get_build_name(self._name)
		container_final_image = f"{container_image_name}:{container_date}"

		ret, result = self._run_buildah(f"unmount {working_container}")
		if ret != 0:
			raise ContainerBuildError("{}: {}".format(os.strerror(ret), result))
		
		cmd = f"commit {working_container} {container_final_image}"
		ret, result = self._run_buildah(cmd)
		if ret != 0:
			raise ContainerBuildError("{}: {}".format(os.strerror(ret), result))
		new_container_id = result.splitlines()[0]

		cmd = f"tag {new_container_id} {container_image_name}:latest"
		ret, result = self._run_buildah(cmd)
		if ret != 0:
			raise ContainerBuildError("{}: {}".format(os.strerror(ret), result))

		print("{}: {} ({})".format(
			click.style("built container", fg="green"),
			container_final_image,
			new_container_id[:12]))

		return True


			




		
	
