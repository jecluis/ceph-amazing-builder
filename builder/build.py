import click
import sys
import shlex
import subprocess
import shutil
from pathlib import Path
from .config import Config, UnknownBuildError


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

	
	def _build(self):
		cfg = self._config.get_config_path()
		cmd = "buildah unshare ./build.sh {} {} {} -c {} --buildname {}".format(
			self._vendor, self._release, self._sources, cfg, self._name
		)
		proc = subprocess.run(shlex.split(cmd), stdout=sys.stdout)
		if proc.returncode != 0:
			click.secho(f"error building: {proc.returncode}", fg="red")
		else:
			click.secho(f"succesfully built", fg="green")
