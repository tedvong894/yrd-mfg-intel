#!/bin/bash
# 构建「长三角制造业情报」原生 macOS App（可重复执行）
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="/Users/tedwong/Applications/长三角制造业情报.app"
ICNS="$HERE/../app-icon.icns"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# 1. 编译二进制
xcrun swiftc -O -o "$APP/Contents/MacOS/yrdintel" "$HERE/main.swift" \
  -framework Cocoa -framework WebKit

# 2. Info.plist
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>长三角制造业情报</string>
  <key>CFBundleDisplayName</key><string>长三角制造业情报</string>
  <key>CFBundleExecutable</key><string>yrdintel</string>
  <key>CFBundleIdentifier</key><string>com.tedwong.yrd-mfg-intel</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>CFBundleURLTypes</key>
  <array>
    <dict>
      <key>CFBundleURLName</key><string>com.tedwong.yrd-mfg-intel</string>
      <key>CFBundleURLSchemes</key>
      <array><string>yrdintel</string></array>
    </dict>
  </array>
</dict>
</plist>
PLIST

# 3. 图标
cp "$ICNS" "$APP/Contents/Resources/AppIcon.icns"

# 3b. 刷新脚本（供 App 内「立即刷新」调用：触发 GitHub Actions 云端采集）
cp "$HERE/../../refresh_via_actions.sh" "$APP/Contents/Resources/refresh_via_actions.sh"
chmod +x "$APP/Contents/Resources/refresh_via_actions.sh"

# 3c. 永久删除脚本（供 App 内 ✕ 按钮调用：写回仓库删除名单 → 云端物理清除）
cp "$HERE/delete_case.sh" "$APP/Contents/Resources/delete_case.sh"
chmod +x "$APP/Contents/Resources/delete_case.sh"

# 4. 签名 + 注册
codesign --force --deep --sign - "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP"
echo "[ok] 已构建: $APP"
