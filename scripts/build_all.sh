#!/bin/bash
set -e

APP_NAME="pinterest-downloader"
VERSION="2.0.0"

echo "Cleaning up before build..."
rm -rf build/ dist/

echo "Building with PyInstaller..."
pyinstaller PinterestDownloader.spec

echo "Preparing DEB package..."
STAGING_DIR="staging_deb"
rm -rf $STAGING_DIR
mkdir -p $STAGING_DIR/usr/bin
mkdir -p $STAGING_DIR/usr/share/applications
mkdir -p $STAGING_DIR/usr/share/icons/hicolor/scalable/apps
mkdir -p $STAGING_DIR/DEBIAN

# Copy files
cp -r dist/$APP_NAME/* $STAGING_DIR/usr/bin/
# The main binary needs to be directly in /usr/bin for easy access, 
# but PyInstaller in 'onedir' mode puts many files there.
# We'll create a wrapper or move everything to /opt later if needed.
# For now, let's keep it simple.

cat > $STAGING_DIR/DEBIAN/control <<EOT
Package: $APP_NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Maintainer: Yuri Schmaltz <yurix@example.com>
Description: Pinterest Board Downloader
 Tool to download images from Pinterest boards via CLI or GUI.
EOT

cat > $STAGING_DIR/usr/share/applications/$APP_NAME.desktop <<EOT
[Desktop Entry]
Type=Application
Name=Pinterest Downloader
Comment=Download images from Pinterest boards
Exec=$APP_NAME
Icon=$APP_NAME
Categories=Utility;Network;
Terminal=false
EOT

cp icon.svg $STAGING_DIR/usr/share/icons/hicolor/scalable/apps/$APP_NAME.svg

echo "Packaging DEB..."
dpkg-deb --build $STAGING_DIR ${APP_NAME}_${VERSION}_amd64.deb

echo "Build complete!"
