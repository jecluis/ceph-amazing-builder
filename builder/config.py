import yaml
from pathlib import Path
from appdirs import user_config_dir  # type: ignore
from typing import Dict, Any, List, Optional
from .utils import print_tree


class UnknownBuildError(Exception):
    def __init__(self, name: str):
        super().__init__(f"unknown build name '{name}'")


class Config:

    _config_dir: Path
    _build_config_dir: Path
    _has_config: bool = False

    _ccache_dir: Optional[Path] = None
    _installs_dir: Optional[Path] = None
    _ccache_default_size: str
    _registry_url: Optional[str] = None
    _registry_is_secure: bool = False

    def __init__(self):
        config_dir = user_config_dir('cab')
        self._config_dir = Path(config_dir)
        self._config_dir.mkdir(0o755, exist_ok=True)
        self._build_config_dir = self._config_dir.joinpath('builds')
        self._build_config_dir.mkdir(0o755, exist_ok=True)
        self._ccache_default_size = '10G'
        self._has_config = self._read_config()

    def _read_config_file(self, config_path: Path) -> Dict[str, Any]:
        assert config_path.exists()
        with config_path.open('r') as fd:
            config_dict: Dict[str, str] = yaml.safe_load(fd)
            return config_dict

    def _read_config(self):
        config_path = self._config_dir.joinpath('config.yaml')
        if not config_path.exists():
            return False

        config_dict = self._read_config_file(config_path)
        if 'global' not in config_dict:
            return False
        global_config = config_dict['global']
        if 'ccache' in global_config:
            ccache_config = global_config['ccache']
            if 'path' in ccache_config:
                self._ccache_dir = Path(ccache_config['path'])
            if 'size' in global_config:
                self._ccache_default_size = ccache_config['size']
        if 'installs' in global_config:
            installs_config = global_config['installs']
            if 'path' in installs_config:
                self._installs_dir = Path(installs_config['path'])
        if 'registry' in global_config:
            registry_config = global_config['registry']
            if 'url' in registry_config:
                self._registry_url = global_config['registry']['url']
            if 'secure' in registry_config:
                self._registry_is_secure = registry_config['secure']

        if not self._installs_dir:
            return False

        # self.print()
        return True

    def has_config(self):
        return self._has_config

    def has_ccache(self):
        return self.get_ccache_dir() is not None

    def has_registry(self):
        return self.get_registry() is not None

    def is_registry_secure(self):
        return self._registry_is_secure

    def get_config_path(self) -> str:
        return str(self._config_dir.joinpath('config.yaml'))

    def get_ccache_dir(self) -> Optional[Path]:
        return self._ccache_dir

    def get_installs_dir(self) -> Path:
        assert self._installs_dir is not None
        return self._installs_dir

    def get_ccache_size(self) -> str:
        return self._ccache_default_size

    def get_registry(self) -> Optional[str]:
        return self._registry_url

    def set_ccache_dir(self, ccache_str: str):
        if not ccache_str:
            self._ccache_dir = None
        else:
            self._ccache_dir = Path(ccache_str).expanduser()

    def set_installs_dir(self, installs_dir: str):
        self._installs_dir = Path(installs_dir).expanduser()

    def set_ccache_size(self, sz: str):
        self._ccache_default_size = sz

    def set_registry(self, registry: str, secure_registry: bool):
        self._registry_url = registry
        self._registry_is_secure = secure_registry

    def _write_config(self):
        assert self._config_dir.exists()
        config_file = 'config.yaml'
        d = {
            'global': {
                'installs': {
                    'path': str(self._installs_dir)
                }
            }
        }
        if self._ccache_dir:
            d['global']['ccache'] = {
                'path': str(self._ccache_dir),
                'size': self._ccache_default_size
            }
        if self._registry_url:
            d['global']['registry'] = {
                'url': self._registry_url,
                'secure': self._registry_is_secure
            }
        path = self._config_dir.joinpath(config_file)
        self._write_config_file(d, path)

    def _write_config_file(self, d: Dict[str, Any], path: Path):
        with path.open('w') as fd:
            yaml.dump(d, stream=fd)
            # json.dump(d, fd)

    def commit(self):
        self._write_config()

    def _get_build_config_path(self, name: str) -> Path:
        return self._build_config_dir.joinpath(f'{name}.yaml')

    def build_exists(self, name: str) -> bool:
        return self._get_build_config_path(name).exists()

    def get_build_config(self, name: str) -> Dict[str, Any]:
        if not self.build_exists(name):
            raise UnknownBuildError(name)

        path = self._get_build_config_path(name)
        build_config = self._read_config_file(path)
        return build_config

    def write_build_config(self, name: str, conf_dict: Dict[str, Any]):
        assert name
        assert conf_dict
        path = self._get_build_config_path(name)
        self._write_config_file(conf_dict, path)

    def get_builds(self) -> List[str]:
        lst = []
        for build in self._build_config_dir.iterdir():
            if build.suffix != '.yaml':
                continue
            lst.append(build.with_suffix('').name)
        return lst

    def remove_build(self, buildname: str) -> bool:
        if not self.build_exists(buildname):
            return True
        buildpath = self._get_build_config_path(buildname)
        assert buildpath.exists()
        buildpath.unlink()
        return True

    def print(self):
        tree = [
            ('config', '', [
                ('installs directory', self.get_installs_dir()),
                ('ccache directory', self.get_ccache_dir(), [
                    ('size', self.get_ccache_size())
                ]),
                ('registry', self._registry_url, [
                    ('secure', self._registry_is_secure)
                ])
            ])
        ]
        print_tree(tree)
