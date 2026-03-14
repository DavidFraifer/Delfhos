import os
from pathlib import Path
from typing import Dict, Optional
from delfhos.errors import EnvironmentKeyError

class EnvLoader:
    def __init__(self):
        self._env_vars: Dict[str, str] = {}
        self._loaded = False
        self._load_env()
    
    def _load_env(self):
        if self._loaded:
            return
            
        env_paths = [
            Path.cwd() / '.env',
            self._find_project_root() / '.env',
            *[Path.cwd().parents[i] / '.env' for i in range(3)]
        ]
        
        for env_path in env_paths:
            if env_path.exists() and env_path.is_file():
                self._parse_env_file(env_path)
                break
        
        self._loaded = True
    
    def _find_project_root(self) -> Path:
        indicators = ['pyproject.toml', 'setup.py', 'requirements.txt', '.git', 'README.md']
        
        for parent in [Path.cwd()] + list(Path.cwd().parents):
            if any((parent / indicator).exists() for indicator in indicators):
                return parent
        
        return Path.cwd()
    
    def _parse_env_file(self, env_path: Path):
        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    
                    key, value = line.split('=', 1)
                    key, value = key.strip(), value.strip()
                    
                    if value.startswith(('"', "'")) and value.endswith(('"', "'")):
                        value = value[1:-1]
                    
                    self._env_vars[key] = value
                    os.environ[key] = value
            
        except Exception:
            pass
    
    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self._env_vars.get(key) or os.environ.get(key) or default
    
    def get_api_key(self, service: str) -> Optional[str]:
        key_mappings = {
            'gemini': ['GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_KEY'],
        }
        
        for key in key_mappings.get(service.lower(), [f"{service.upper()}_API_KEY"]):
            if value := self.get(key):
                return value
        
        return None
    
    def require_api_key(self, service: str) -> str:
        if not (api_key := self.get_api_key(service)):
            raise EnvironmentKeyError(key=f"{service.upper()}_API_KEY")
        return api_key

_env_loader = None

def get_env_loader() -> EnvLoader:
    global _env_loader
    if _env_loader is None:
        _env_loader = EnvLoader()
    return _env_loader

def get_api_key(service: str) -> Optional[str]:
    return get_env_loader().get_api_key(service)

def require_api_key(service: str) -> str:
    return get_env_loader().require_api_key(service)
