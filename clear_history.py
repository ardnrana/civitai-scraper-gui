"""
Clear Download History Utility
Provides options to clear different parts of the download history
"""

import os
import sqlite3
from pathlib import Path
import shutil

def clear_database():
    """Clear all entries from the database"""
    db_path = Path("downloads/download_history.db")
    if db_path.exists():
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Clear all tables
            cursor.execute("DELETE FROM downloads")
            cursor.execute("DELETE FROM metadata")
            cursor.execute("DELETE FROM generation_params")
            cursor.execute("DELETE FROM image_tags")
            cursor.execute("DELETE FROM tags")

            conn.commit()
            conn.close()

            print("✅ Database cleared successfully!")
            print("   - All download records removed")
            print("   - All metadata removed")
            print("   - All tags removed")
            return True
        except Exception as e:
            print(f"❌ Error clearing database: {e}")
            return False
    else:
        print("ℹ️  No database file found")
        return True

def delete_database():
    """Delete the entire database file"""
    db_path = Path("downloads/download_history.db")
    if db_path.exists():
        try:
            os.remove(db_path)
            print("✅ Database file deleted!")
            print("   A new database will be created on next run")
            return True
        except Exception as e:
            print(f"❌ Error deleting database: {e}")
            return False
    else:
        print("ℹ️  No database file found")
        return True

def clear_text_log():
    """Clear the old text log file"""
    log_path = Path("downloads/download_log.txt")
    backup_path = Path("downloads/download_log.txt.bak")

    removed = False

    if log_path.exists():
        try:
            os.remove(log_path)
            print("✅ Text log file removed")
            removed = True
        except Exception as e:
            print(f"❌ Error removing text log: {e}")

    if backup_path.exists():
        try:
            os.remove(backup_path)
            print("✅ Text log backup removed")
            removed = True
        except Exception as e:
            print(f"❌ Error removing backup: {e}")

    if not removed:
        print("ℹ️  No text log files found")

    return True

def delete_all_files():
    """Delete all downloaded files"""
    downloads_dir = Path("downloads")

    if not downloads_dir.exists():
        print("ℹ️  No downloads directory found")
        return True

    print("\n⚠️  WARNING: This will delete ALL downloaded files!")
    confirm = input("Type 'DELETE ALL FILES' to confirm: ")

    if confirm != "DELETE ALL FILES":
        print("❌ Cancelled - files not deleted")
        return False

    try:
        # Count files first
        file_count = 0
        for root, dirs, files in os.walk(downloads_dir):
            file_count += len(files)

        print(f"\n🗑️  Deleting {file_count} files...")

        # Delete everything except the database
        for item in downloads_dir.iterdir():
            if item.name == "download_history.db":
                continue  # Keep database

            if item.is_file():
                os.remove(item)
            elif item.is_dir():
                shutil.rmtree(item)

        print("✅ All files deleted successfully!")
        print("   (Database kept for reference)")
        return True

    except Exception as e:
        print(f"❌ Error deleting files: {e}")
        return False

def delete_everything():
    """Delete EVERYTHING - complete fresh start"""
    downloads_dir = Path("downloads")

    if not downloads_dir.exists():
        print("ℹ️  No downloads directory found")
        return True

    print("\n⚠️  EXTREME WARNING: This will delete EVERYTHING!")
    print("   - All downloaded files")
    print("   - All metadata")
    print("   - The entire database")
    print("   - All folder structure")
    confirm = input("\nType 'DELETE EVERYTHING' to confirm: ")

    if confirm != "DELETE EVERYTHING":
        print("❌ Cancelled - nothing deleted")
        return False

    try:
        shutil.rmtree(downloads_dir)
        print("✅ Everything deleted successfully!")
        print("   Complete fresh start - downloads folder removed")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    print("=" * 60)
    print("  Civitai Scraper - Clear History Utility")
    print("=" * 60)
    print()
    print("Choose what to clear:")
    print()
    print("1. Clear database records only (keep files)")
    print("   - Removes download history from database")
    print("   - Files remain on disk")
    print("   - You can re-scan them later")
    print()
    print("2. Delete database file completely")
    print("   - Removes entire database")
    print("   - Fresh database created on next run")
    print("   - Files remain on disk")
    print()
    print("3. Clear old text log files")
    print("   - Removes download_log.txt and backup")
    print("   - Only if you used old text-based logging")
    print()
    print("4. Delete ALL downloaded files (DANGER!)")
    print("   - Deletes all images, videos, metadata")
    print("   - Keeps database for reference")
    print("   - Cannot be undone!")
    print()
    print("5. Delete EVERYTHING - Complete reset (EXTREME DANGER!)")
    print("   - Deletes entire downloads folder")
    print("   - Complete fresh start")
    print("   - Cannot be undone!")
    print()
    print("6. Exit without changes")
    print()

    choice = input("Enter choice (1-6): ").strip()

    print("\n" + "=" * 60)

    if choice == "1":
        print("Clearing database records...\n")
        clear_database()
    elif choice == "2":
        print("Deleting database file...\n")
        delete_database()
    elif choice == "3":
        print("Clearing text log files...\n")
        clear_text_log()
    elif choice == "4":
        delete_all_files()
    elif choice == "5":
        delete_everything()
    elif choice == "6":
        print("Exiting without changes")
    else:
        print("❌ Invalid choice")

    print("\n" + "=" * 60)
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()
