"""
Settings Manager for Civitai Scraper
Handles configuration persistence and validation
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

class SettingsManager:
    """Manage application settings with JSON persistence"""

    DEFAULT_SETTINGS = {
        'download_path': 'downloads',
        'app_data_path': None,  # Will default to script directory
        'workers': 5,
        'api_key': '',
        'organize_by_nsfw': True,
        'log_level': 'INFO',
        'enable_retry': True,
        'max_retries': 3
    }

    def __init__(self, config_file: str = 'config.json'):
        """Initialize settings manager

        Args:
            config_file: Path to config JSON file (relative to app directory)
        """
        # Determine app directory (where the script is located)
        self.app_dir = Path(__file__).parent.resolve()
        self.config_file = self.app_dir / config_file

        # Load or create settings
        self.settings = self._load_settings()

        # Set default app_data_path if not specified
        if not self.settings.get('app_data_path'):
            self.settings['app_data_path'] = str(self.app_dir)
            self.save()

    def _load_settings(self) -> Dict[str, Any]:
        """Load settings from JSON file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # Merge with defaults to ensure all keys exist
                    settings = self.DEFAULT_SETTINGS.copy()
                    settings.update(loaded)
                    return settings
            except Exception as e:
                print(f"Warning: Could not load config from {self.config_file}: {e}")
                print("Using default settings")

        return self.DEFAULT_SETTINGS.copy()

    def save(self) -> bool:
        """Save current settings to JSON file"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving settings: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value"""
        return self.settings.get(key, default)

    def set(self, key: str, value: Any) -> bool:
        """Set a setting value and save"""
        self.settings[key] = value
        return self.save()

    def update(self, updates: Dict[str, Any]) -> bool:
        """Update multiple settings at once"""
        self.settings.update(updates)
        return self.save()

    def get_download_path(self) -> Path:
        """Get download path as Path object"""
        download_path = self.settings.get('download_path', 'downloads')

        # If relative path, make it absolute relative to app directory
        path = Path(download_path)
        if not path.is_absolute():
            path = self.app_dir / path

        return path

    def get_app_data_path(self) -> Path:
        """Get app data path (for database, logs, etc.)"""
        app_data = self.settings.get('app_data_path')
        if not app_data:
            return self.app_dir
        return Path(app_data)

    def get_database_path(self) -> Path:
        """Get full path to database file"""
        # Database always stays in app data directory
        return self.get_app_data_path() / 'download_history.db'

    def validate_paths(self) -> Dict[str, Any]:
        """Validate all configured paths

        Returns:
            Dict with validation results
        """
        results = {
            'valid': True,
            'errors': [],
            'warnings': []
        }

        # Check download path
        download_path = self.get_download_path()
        try:
            download_path.mkdir(parents=True, exist_ok=True)
            if not download_path.exists():
                results['errors'].append(f"Cannot create download path: {download_path}")
                results['valid'] = False
            elif not os.access(download_path, os.W_OK):
                results['errors'].append(f"Download path not writable: {download_path}")
                results['valid'] = False
        except Exception as e:
            results['errors'].append(f"Download path error: {e}")
            results['valid'] = False

        # Check app data path
        app_data = self.get_app_data_path()
        try:
            app_data.mkdir(parents=True, exist_ok=True)
            if not app_data.exists():
                results['errors'].append(f"Cannot create app data path: {app_data}")
                results['valid'] = False
            elif not os.access(app_data, os.W_OK):
                results['errors'].append(f"App data path not writable: {app_data}")
                results['valid'] = False
        except Exception as e:
            results['errors'].append(f"App data path error: {e}")
            results['valid'] = False

        return results

    def get_all(self) -> Dict[str, Any]:
        """Get all settings as dictionary"""
        return self.settings.copy()

    def reset_to_defaults(self) -> bool:
        """Reset all settings to defaults"""
        self.settings = self.DEFAULT_SETTINGS.copy()
        return self.save()
