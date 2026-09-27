#!/bin/zsh
set -eu
TASK_ROOT="${0:A:h:h}"
cd "$TASK_ROOT"
TASK_BUILD="$TASK_ROOT/.skycompanion-live/mobile-loopback-check"
mkdir -p "$TASK_BUILD"
xcrun swiftc -emit-library -emit-module -module-name CaptureCore ios/CaptureCore/Sources/CaptureCore/*.swift -o "$TASK_BUILD/libCaptureCore.dylib" -emit-module-path "$TASK_BUILD/CaptureCore.swiftmodule" -module-cache-path "$TASK_BUILD/cache"
xcrun swiftc -O -I "$TASK_BUILD" -L "$TASK_BUILD" -lCaptureCore ios/OnDevice/LocalProtocol.swift ios/OnDevice/LocalRecordingAudio.swift ios/OnDevice/RecordingAudioRelay.swift ios/OnDevice/LoopbackChannel.swift ios/OnDevice/RecoveringBroadcastChannel.swift scripts/test_mobile_loopback.swift -o "$TASK_BUILD/test-mobile-loopback" -module-cache-path "$TASK_BUILD/cache" -Xlinker -rpath -Xlinker "$TASK_BUILD"
if [[ "${1:-}" != "--build-only" ]]; then
  "$TASK_BUILD/test-mobile-loopback"
fi
