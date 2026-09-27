#!/usr/bin/env python3
"""Run actual SkyCompanion Form interaction tests in an iOS simulator.

Generate only a temporary UI-test target; the production project and models stay intact.
"""
from pathlib import Path
import argparse
import hashlib
import json
import plistlib
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--device", required=True)
parser.add_argument("--result", required=True)
parser.add_argument("--inspect", action="store_true")
args = parser.parse_args()
project = json.loads(subprocess.check_output([
    "plutil", "-convert", "json", "-o", "-", str(root / "ios/SkyCompanionCapture.xcodeproj/project.pbxproj")]))
objects = project["objects"]

def add(identity, **properties):
    key = hashlib.sha256(("area-ui-test-" + identity).encode()).hexdigest()[:24].upper()
    objects[key] = properties
    return key

app = next(k for k, v in objects.items() if v.get("isa") == "PBXNativeTarget" and v["name"] == "SkyCompanion")
main = objects[project["rootObject"]]
main["projectDirPath"] = ""
objects[main["mainGroup"]].update(path=str(root / "ios"), sourceTree="<absolute>")
for obj in list(objects.values()):
    if obj.get("isa") == "XCLocalSwiftPackageReference":
        obj["relativePath"] = str(root / "ios" / obj["relativePath"])
    if obj.get("sourceTree") == "SOURCE_ROOT" and "path" in obj:
        obj.update(path=str(root / "ios" / obj["path"]), sourceTree="<absolute>")
    if obj.get("isa") == "XCBuildConfiguration" and "INFOPLIST_FILE" in obj["buildSettings"]:
        obj["buildSettings"]["INFOPLIST_FILE"] = str(root / "ios" / obj["buildSettings"]["INFOPLIST_FILE"])
source = add("source", isa="PBXFileReference", lastKnownFileType="sourcecode.swift",
             path=str(root / "ios/UITests/VideoAreaUITests.swift"), sourceTree="<absolute>")
build = add("build", isa="PBXBuildFile", fileRef=source)
sources = add("sources", isa="PBXSourcesBuildPhase", buildActionMask=2147483647, files=[build], runOnlyForDeploymentPostprocessing=0)
frameworks = add("frameworks", isa="PBXFrameworksBuildPhase", buildActionMask=2147483647, files=[], runOnlyForDeploymentPostprocessing=0)
product = add("product", isa="PBXFileReference", explicitFileType="wrapper.cfbundle", path="VideoAreaUITests.xctest", sourceTree="BUILT_PRODUCTS_DIR")
config = add("debug", isa="XCBuildConfiguration", name="Debug", buildSettings={
    "PRODUCT_NAME": "$(TARGET_NAME)", "PRODUCT_BUNDLE_IDENTIFIER": "com.stanley.skycompanion.AreaUITests",
    "TEST_TARGET_NAME": "SkyCompanion", "GENERATE_INFOPLIST_FILE": "YES",
    "SDKROOT": "iphoneos", "SUPPORTED_PLATFORMS": "iphoneos iphonesimulator",
    "TARGETED_DEVICE_FAMILY": "1", "IPHONEOS_DEPLOYMENT_TARGET": "18.0", "SWIFT_VERSION": "5.0",
    "CODE_SIGNING_ALLOWED": "NO", "LD_RUNPATH_SEARCH_PATHS": ["$(inherited)", "@executable_path/Frameworks", "@loader_path/Frameworks"]})
configs = add("configs", isa="XCConfigurationList", buildConfigurations=[config], defaultConfigurationIsVisible=0, defaultConfigurationName="Debug")
proxy = add("proxy", isa="PBXContainerItemProxy", containerPortal=project["rootObject"], proxyType=1, remoteGlobalIDString=app, remoteInfo="SkyCompanion")
dependency = add("dependency", isa="PBXTargetDependency", target=app, targetProxy=proxy)
target = add("target", isa="PBXNativeTarget", name="VideoAreaUITests", productName="VideoAreaUITests",
             productType="com.apple.product-type.bundle.ui-testing", productReference=product,
             buildConfigurationList=configs, buildPhases=[sources, frameworks], buildRules=[], dependencies=[dependency])
main["targets"].append(target)
main["attributes"]["TargetAttributes"][target] = {"TestTargetID": app}
objects[main["mainGroup"]]["children"].append(source)
objects[main["productRefGroup"]]["children"].append(product)
with tempfile.TemporaryDirectory(prefix="sky-area-uitest-") as directory:
    path = Path(directory) / "SkyCompanionCapture.xcodeproj"
    path.mkdir()
    (path / "project.pbxproj").write_bytes(plistlib.dumps(project))
    scheme = path / "xcshareddata/xcschemes/AreaRegression.xcscheme"
    scheme.parent.mkdir(parents=True)
    reference = f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{target}" BuildableName="VideoAreaUITests.xctest" BlueprintName="VideoAreaUITests" ReferencedContainer="container:SkyCompanionCapture.xcodeproj"/>'
    app_reference = f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{app}" BuildableName="SkyCompanion.app" BlueprintName="SkyCompanion" ReferencedContainer="container:SkyCompanionCapture.xcodeproj"/>'
    scheme.write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<Scheme version="1.3"><BuildAction buildImplicitDependencies="YES"><BuildActionEntries>
<BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="NO" buildForArchiving="NO" buildForAnalyzing="YES">{app_reference}</BuildActionEntry>
<BuildActionEntry buildForTesting="YES" buildForRunning="NO" buildForProfiling="NO" buildForArchiving="NO" buildForAnalyzing="YES">{reference}</BuildActionEntry>
</BuildActionEntries></BuildAction><TestAction buildConfiguration="Debug" shouldUseLaunchSchemeArgsEnv="YES"><Testables>
<TestableReference skipped="NO">{reference}</TestableReference></Testables></TestAction>
<LaunchAction buildConfiguration="Debug"><BuildableProductRunnable runnableDebuggingMode="0">{app_reference}</BuildableProductRunnable></LaunchAction></Scheme>''')
    if args.inspect:
        subprocess.run(["xcodebuild", "-project", str(path), "-scheme", "AreaRegression", "-sdk", "iphonesimulator", "-showBuildSettings"], check=True)
        raise SystemExit(0)
    subprocess.run(["xcodebuild", "-project", str(path), "-scheme", "AreaRegression", "-destination",
                    f"platform=iOS Simulator,id={args.device}", "-derivedDataPath", "/tmp/sky-area-ui-tests",
                    "-resultBundlePath", str(Path(args.result).resolve()), "-parallel-testing-enabled", "NO",
                    "CODE_SIGNING_ALLOWED=NO", "test"], check=True, timeout=300)
