#!/bin/zsh
# Builds SttarkClaudeKit.app into ./build. Runs on Apple Silicon and Intel Macs, macOS 14 or later.
# The version is 1.<number of commits>, so every build of main is numbered higher than the last.
# It's signed with a "Sttark Effort Signing" certificate when this Mac has one,
# which lets an update check the new copy came from the same signer. Without it the build is signed
# ad hoc, and macOS asks again for any permission the Chrome approver was given after each install.
set -e
cd "$(dirname "$0")"
command -v swiftc >/dev/null || { echo "Needs Apple's command line tools. Run: xcode-select --install"; exit 1; }
APP=build/SttarkClaudeKit.app
# the hooks run on macOS's own Python (3.9), which rejects some newer syntax
for f in Resources/hooks/*.py; do /usr/bin/python3 -c 'import ast,sys; ast.parse(open(sys.argv[1]).read(), sys.argv[1])' "$f" || exit 1; done
BUILD=${BUILD:-$(git rev-list --count HEAD 2>/dev/null || echo 0)}
rm -rf build
mkdir -p $APP/Contents/MacOS $APP/Contents/Resources
for arch in arm64 x86_64; do
  swiftc -O -swift-version 5 -target $arch-apple-macos14.0 Sources/*.swift -o build/SttarkClaudeKit-$arch
done
lipo -create build/SttarkClaudeKit-arm64 build/SttarkClaudeKit-x86_64 -output $APP/Contents/MacOS/SttarkClaudeKit
rm build/SttarkClaudeKit-arm64 build/SttarkClaudeKit-x86_64
# the Chrome approver, a separate small program the app starts at login when its switch is on
for arch in arm64 x86_64; do
  swiftc -O -swift-version 5 -target $arch-apple-macos14.0 Helpers/ChromeApprover.swift -o build/ChromeApprover-$arch
done
lipo -create build/ChromeApprover-arm64 build/ChromeApprover-x86_64 -output $APP/Contents/MacOS/SttarkChromeApprover
rm build/ChromeApprover-arm64 build/ChromeApprover-x86_64
cp Info.plist $APP/Contents/Info.plist
cp -R Resources/* $APP/Contents/Resources/
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $BUILD" -c "Set :CFBundleShortVersionString 1.$BUILD" $APP/Contents/Info.plist
SIGN_ID=${SIGN_ID:-$(security find-identity -v -p codesigning 2>/dev/null | awk '/"Sttark Effort Signing"/ {print $2; exit}')}
SIGN=${SIGN_ID:--}
[[ -n $SIGN_ID ]] || echo "No Sttark Effort Signing certificate here, so this build is signed ad hoc."
# the helper first: it has its own identity, which is what macOS's Accessibility permission is tied to
codesign --force --sign $SIGN --identifier com.sttark.chrome-approver $APP/Contents/MacOS/SttarkChromeApprover
codesign --force --sign $SIGN --identifier com.sttark.sttark-claude-kit $APP
echo "built $APP, version 1.$BUILD"
