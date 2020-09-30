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
from typing import Tuple, List


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


	def _remove_build(self) -> bool:
		builds_dir = self._config.get_builds_dir()
		buildpath = builds_dir.joinpath(self._name)
		click.secho(
			f"=> remove install directory at {buildpath}", fg="yellow")
		if not buildpath.exists() or not buildpath.is_dir():
			click.secho("  - build path not found", fg="green")
			return True
		try:
			shutil.rmtree(buildpath)
		except Exception as e:
			click.secho(f"error removing install directory: {str(e)}")
			return False
		return True


	def _remove_containers(self) -> bool:
		imgs: List[ContainerImage] = Containers.find_build_images(self._name)
		imgs = sorted(imgs, key=lambda img: img._created, reverse=True)
		for img in imgs:
			if not Containers.rm_image(img):
				return False
		return True


	def _destroy(self, remove_build=False, remove_containers=False) -> bool:

		success = True
		while True:
			if remove_build:
				if not self._remove_build():
					success = False
					break

			if remove_containers:
				if not self._remove_containers():
					success = False
					break
			break
		if not success:
			return False
		return self._config.remove_build(self._name)


	@classmethod
	def destroy(cls, config: Config, name: str,
	            remove_build=False,
	            remove_containers=False) -> bool:
		build = Build(config, name)
		return build._destroy(remove_build, remove_containers)


	@classmethod
	def build(cls, config: Config, name: str, nuke_build=False,
	          with_debug=False, with_tests=False,
	          with_fresh_build=False):
		if not config.build_exists(name):
			raise UnknownBuildError(name)
		build = Build(config, name)

		# nuke an existing build install directory; force reinstall.
		if nuke_build:
			install_path: Path = \
				config.get_builds_dir().joinpath(build._name)
			click.secho(
				f"=> removing install path at {install_path}", fg="yellow")
			if install_path.exists():
				assert install_path.is_dir()
				shutil.rmtree(install_path)
	
		build._build(with_debug=with_debug, with_tests=with_tests,
		             with_fresh_build=with_fresh_build)


	def _build(self, do_build=True, do_container=True,
	           with_debug=False, with_tests=False,
	           with_fresh_build=False):

		ccache_path: Path = None
		build_path: Path = None
		base_build_image: str = None

		# prepare ccache
		if self._config.has_ccache():
			ccache_path: Path =	self._config.get_ccache_dir().joinpath(
			                             f"{self._vendor}/{self._release}")
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
	
		if do_build:
			if not self._perform_build(build_path, ccache_path,
			                           with_debug, with_tests,
	                                   with_fresh_build):
				raise BuildError()

		if do_container:
			if not self._build_container(build_path, base_build_image):
				raise ContainerBuildError()


	def _perform_build(self, build_path: Path, ccache_path: Path,
	                   with_debug: bool, with_tests: bool,
	                   with_fresh_build: bool
	) -> bool:
		""" Performs the actual, containerized build from specified sources.

			The build process is based on running a specific build container,
			based on a given release, against the build's sources, and finally
			installing the binaries into the build's build path.

			build_path is the location of the directory where our final build
			will live.

			ccache_path is the location for the vendor/release ccache.

			with_debug will instruct the build script to build with debug
			symbols.

			with_tests will instruct the build script to build the tests.
			
		"""

		click.secho("==> building sources", fg="cyan")
		cprint("      vendor", self._vendor)
		cprint("     release", self._release)
		cprint("sources path", self._sources)
		cprint("  build path", build_path)
		cprint(" ccache path", ccache_path)
		cprint("  with debug", with_debug)
		cprint("  with tests", with_tests)


		build_image = \
			Containers.find_base_build_image(self._vendor, self._release)
		if not build_image:
			raise BuildError("unable to find base build image")

		bindir = Path.cwd().joinpath("bin")
		extra_args = []

		if with_debug:
			extra_args.append("--with-debug")
		if with_tests:
			extra_args.append("--with-tests")
		if with_fresh_build:
			extra_args.append("--fresh-build")

		cmd = f"podman run -it --userns=keep-id " \
			  f"-v {bindir}:/build/bin " \
			  f"-v {self._sources}:/build/src " \
			  f"-v {str(build_path)}:/build/out"
		
		if ccache_path is not None:
			cmd += f" -v {str(ccache_path)}:/build/ccache"
			extra_args.append("--with-ccache")

		# currently, the build image's entrypoint requires an argument to
		# perform a build using ccache.
		cmd += f" {build_image}"
		extra_args_str = ' '.join(extra_args)
		cmd += f" {extra_args_str}"
		
		# cprint("build cmd", cmd)
		# sys.exit(1)
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

		click.secho("==> building container", fg="cyan")
		cprint("from build path", build_path)
		cprint("       based on", base_image)

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

		new_container_img: ContainerImage = \
			Containers.find_build_image_latest(self._name)

		print("{}: {} ({}) {}".format(
			click.style("built container", fg="green"),
			container_final_image,
			new_container_id[:12],
			new_container_img.get_size_str()))

		return True


			




		
	
