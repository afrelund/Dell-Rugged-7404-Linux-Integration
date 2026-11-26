#!/bin/sh
# Build the .deb into ./dist (requires dpkg-deb).
set -e
cd "$(dirname "$0")"
ver=$(sed -n 's/^Version: //p' dell-rugged-7404/DEBIAN/control)
mkdir -p ../dist
chmod 755 dell-rugged-7404/DEBIAN/post* dell-rugged-7404/DEBIAN/prerm \
    dell-rugged-7404/usr/bin/* dell-rugged-7404/usr/sbin/*
dpkg-deb --root-owner-group --build dell-rugged-7404 "../dist/dell-rugged-7404_${ver}_all.deb"
