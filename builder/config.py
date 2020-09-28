import json
from pathlib import Path
from appdirs import user_config_dir
from typing import Dict, Any, List


class UnknownBuildError(Exception):
	def __init__(self, name: str):
		super().__init__(f"unknown build name '{name}'")


class Config:

	_config_dir: Path = None
	_build_config_dir: Path = None
	_has_config: bool = False

	_ccache_dir: Path = None
	_builds_dir: Path = None

	_ccache_default_size: str = None

	def __init__(self):
		config_dir = user_config_dir('cab')
		self._config_dir = Path(config_dir)
		self._config_dir.mkdir(0o755, exist_ok=True)
		self._build_config_dir = self._config_dir.joinpath('builds')
		self._build_config_dir.mkdir(0o755, exist_ok=True)
		self._ccache_default_size = '10G'
		self._has_config = self._read_config()


	def _read_config(self) -> bool:
		config_path = self._config_dir.joinpath('config.json')
		# print(f"config path: {config_path}")
		if not config_path.exists():
			return False
	
		# print("reading config file")
		with config_path.open('r') as fd:
			config_dict: Dict[str, str] = json.load(fd)
			if 'ccache' in config_dict:
				self._ccache_dir = Path(config_dict['ccache'])
			if 'builds' in config_dict:
				self._builds_dir = Path(config_dict['builds'])
			if 'ccache_size' in config_dict:
				self._ccache_default_size = config_dict['ccache_size']

		if not self._builds_dir:
			return False
		return True


	def has_config(self):
		return self._has_config

	def has_ccache(self):
		return self.get_ccache_dir is not None

	def get_config_path(self) -> str:
		return str(self._config_dir.joinpath('config.json'))

	def get_ccache_dir(self) -> Path:
		return self._ccache_dir
	
	def get_builds_dir(self) -> Path:
		return self._builds_dir

	def get_ccache_size(self) -> int:
		return self._ccache_default_size

	def set_ccache_dir(self, ccache_str: str):
		self._ccache_dir = Path(ccache_str).expanduser()

	def set_builds_dir(self, builds_dir: str):
		self._builds_dir = Path(builds_dir).expanduser()

	
	def _write_config(self):
		assert self._config_dir.exists()
		config_file = 'config.json'
		d = {
				'ccache': str(self._ccache_dir),
				'builds': str(self._builds_dir)
		}
		path = self._config_dir.joinpath(config_file)
		self._write_config_file(d, path)


	def _write_config_file(self, d: Dict[str, Any], path: Path):
		with path.open('w') as fd:
			json.dump(d, fd)


	def commit(self):
		self._write_config()

	def _get_build_config_path(self, name: str) -> Path:
		return self._build_config_dir.joinpath(f'{name}.json')
	
	def build_exists(self, name: str) -> bool:
		return self._get_build_config_path(name).exists()

	def get_build_config(self, name: str) -> Dict[str, Any]:
		if not self.build_exists(name):
			raise UnknownBuildError(name)

		path = self._get_build_config_path(name)
		build_config = None
		with path.open('r') as fd:
			build_config = json.load(fd)
		return build_config

	def write_build_config(self, name: str, conf_dict: Dict[str, Any]):
		assert name
		assert conf_dict		
		path = self._get_build_config_path(name)
		self._write_config_file(conf_dict, path)

	def get_builds(self) -> List[str]:
		lst = []
		for build in self._build_config_dir.iterdir():
			if build.suffix != '.json':
				continue
			lst.append(build.with_suffix('').name)
		return lst

	def remove_build(self, buildname: str):
		if not self.build_exists(buildname):
			return
		buildpath = self._get_build_config_path(buildname)
		assert buildpath.exists()
		buildpath.unlink()


	def print(self):
		print(f"ccache directory: {self.get_ccache_dir()}")
		print(f"builds directory: {self.get_builds_dir()}")
