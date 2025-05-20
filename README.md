# A set of tools for using simpleperf

## GUI Tools for capturing data using simpleperf

Better not use it as a black box, use it as ref for your own tool. Lot's of code are vibe coded to suit my own need.

GUI/deps/  
├── extras/   for things like gecko_profile_generator.py  
├── jbr/      for running java tools  
├── ndk/      currently using ndk r23b  
└── other/

**extras** can be obtained using `git clone --branch android-14.0.0_r23 https://android.googlesource.com/platform/system/extras --depth 1`

**other/** contains:
* config.json, which contains sensitive info, like keystore, password, package name
* ManifestEditor-2.0.jar, for make the package debuggable, from https://github.com/WindySha/ManifestEditor
* apksigner.jar
* zipalign.exe

build and deploy with deploy.bat

## Tools for viewing the data 