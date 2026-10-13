#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR/app"
DATA_DIR="$DIR/data" node --no-warnings server.js --open
