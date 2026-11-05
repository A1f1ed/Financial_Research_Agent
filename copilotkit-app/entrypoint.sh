#!/bin/bash
set -e

# Source checkout entry point; run npm ci and npm run build beforehand.
cd "$(dirname "$0")"
exec npm run start:all
