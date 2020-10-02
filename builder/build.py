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
from .utils import print_tree, print_table, pwarn
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

	_with_debug: bool = False
	_with_tests: bool = False

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

		if 'build' in build_config:
			if 'debug' in build_config['build']:
				self._with_debug = build_config['build']['debug']
			if 'tests' in build_config['build']:
				self._with_tests = build_config['build']['tests']


	@classmethod
	def create(cls, config, name, vendor, release, sources,
	           with_debug=False, with_tests=False):
		conf_dict = {
			'name': name,
			'vendor': vendor,
			'release': release,
			'sources': sources,
			'build': {
				'debug': with_debug,
				'tests': with_tests
			}
		}
		config.write_build_config(name, conf_dict)
		return Build(config, name)

	@property
	def with_debug(self):
		return self._with_debug

	@property
	def with_tests(self):
		return self._with_tests

	def get_install_path(self) -> Path:
		installs = self._config.get_installs_dir()
		return installs.joinpath(self._name)

	def get_install_dir(self) -> str:
		return str(self.get_install_path())

	def get_sources_dir(self) -> str:
		return self._sources

	def print(self, with_prefix=False, verbose=False):
		tree = [
			('buildname', self._name, [
				('vendor', self._vendor),
				('release', self._release),
				('sources', self._sources),
				('install', self.get_install_dir()),
				('build', '', [
					('with debug', self.with_debug),
					('with tests', self.with_tests)
				])
			])
		]
		print_tree(tree)


	def _remove_install(self) -> bool:
		installpath = self.get_install_path()		
		if not installpath.exists() or not installpath.is_dir():
			click.secho("  - build path not found", fg="green")
			return True
		try:
			shutil.rmtree(installpath)
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


	def _destroy(self, remove_install=False, remove_containers=False) -> bool:

		success = True
		while True:
			if remove_install:
				installpath = self.get_install_path()
				pwarn(f"=> remove install directory at {installpath}")
				if not self._remove_install():
					success = False
					break

			if remove_containers:
				pwarn(f"=> remove container images")
				if not self._remove_containers():
					success = False
					break
			break
		if not success:
			return False
		return self._config.remove_build(self._name)


	@classmethod
	def destroy(cls, config: Config, name: str,
	            remove_install=False,
	            remove_containers=False) -> bool:
		build = Build(config, name)
		return build._destroy(remove_install, remove_containers)


	@classmethod
	def build(cls, config: Config, name: str, nuke_install=False,
	          with_fresh_build=False):
		if not config.build_exists(name):
			raise UnknownBuildError(name)
		build = Build(config, name)

		# nuke an existing build install directory; force reinstall.
		if nuke_install:
			install_path: Path = \
				config.get_builds_dir().joinpath(build._name)
			click.secho(
				f"=> removing install path at {install_path}", fg="yellow")
			if install_path.exists():
				assert install_path.is_dir()
				shutil.rmtree(install_path)
	
		build._build(with_fresh_build=with_fresh_build)


	def _build(self, do_build=True, do_container=True,
	           with_fresh_build=False):

		ccache_path: Path = None
		install_path: Path = None
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
		install_path = self.get_install_path()
		install_path.mkdir(exist_ok=True)

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
			if not self._perform_build(install_path, ccache_path,
	                                   with_fresh_build):
				raise BuildError()

		if do_container:
			if not self._build_container(install_path, base_build_image):
				raise ContainerBuildError()


	def _perform_build(self, install_path: Path, ccache_path: Path,
	                   with_fresh_build: bool
	) -> bool:
		""" Performs the actual, containerized build from specified sources.

			The build process is based on running a specific build container,
			based on a given release, against the build's sources, and finally
			installing the binaries into the build's build path.

			install_path is the location of the directory where our final build
			will live.

			ccache_path is the location for the vendor/release ccache.

			with_debug will instruct the build script to build with debug
			symbols.

			with_tests will instruct the build script to build the tests.
			
		"""

		click.secho("==> building sources", fg="cyan")
		tbl = [
			("vendor", self._vendor),
			("release", self._release),
			("sources path", self._sources),
			("install path", install_path),
			("ccache path", ccache_path),
			("with debug", self._with_debug),
			("with tests", self._with_tests)
		]
		print_table(tbl, color="cyan")


		build_image = \
			Containers.find_base_build_image(self._vendor, self._release)
		if not build_image:
			raise BuildError("unable to find base build image")

		bindir = Path.cwd().joinpath("bin")
		extra_args = []

		if self.with_debug:
			extra_args.append("--with-debug")
		if self.with_tests:
			extra_args.append("--with-tests")
		if with_fresh_build:
			extra_args.append("--fresh-build")

		cmd = f"podman run -it --userns=keep-id " \
			  f"-v {bindir}:/build/bin " \
			  f"-v {self._sources}:/build/src " \
			  f"-v {str(install_path)}:/build/out"
		
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
	                     install_path: Path,
						 base_image: str
	) -> bool:

		click.secho("==> building container", fg="cyan")
		print_table([
			("from build path", install_path),
			("based on", base_image)
		], color="cyan")
		
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
			  f"{str(install_path)}/ {str(mnt_path)}"
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


			




		
	
