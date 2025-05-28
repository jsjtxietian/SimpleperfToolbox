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
### resolve_stack.py
This file has the following function:

* Get the data from gecko json file from simpleperf's output (see [View the profile](https://android.googlesource.com/platform/system/extras/+/master/simpleperf/doc/view_the_profile.md)), get the raw stack trace, see `resolve_stack`
* Trying to divide the samples into frames in the following steps:
  * Get the raw stack trace using `resolve_stack`
  * Label each of them to several categories using stack trace using some pre-defined metrics, like `FixedUpdate`, `Update`, `Render`, etc. Refer to the Unity profiler to see the ground truth of function order, a typical frame should go like: `FixedUpdate` =>`Physics`=>`Update`=>`LateUpdate` =>`Render`, I intentionally dropped some maker like `DirectorManager` or `ParticleSystem` because they tend to take less time in my experimental data, but it's easy to add them back. Note regex based labelling requires hand-tuning, but it works for the most time. Also I do them in order because it's a string based regex, otherwise the same sample might belongs to several categories.
  * Transform the sample data to merge the same category (a little like RLE) for later use.
  * "Compress" the transformed data, since the stacks might be broken (see [Simpleperf](https://android.googlesource.com/platform/system/extras/+/master/simpleperf/doc/README.md#fix-broken-dwarf-based-call-graph)). For example, situations like `Render=>Other=>Render` will happen because `Other` actually belongs to `Render` but the stack is broken so the label metric failed, I choose to merge the middle `Other` to `Render` if two `Render` is too close that both must belong to the same frame.
  * Use the sequence order `FixedUpdate`=>`Update`=>`LateUpdate` =>`Render` to divide frame, `Physics` maybe called by game logic code so not very robust. Use `Render` as boundary.

I also tried to divide based on `eglSwapBuffers` but that works badly for high-end phone when sample rate is low, like 1000. Also it's the main thread that I care about, so I choose to divide the main thread.

Also there are some consts to be tuned, I should make it more flexible, low-end phones and high-end phones should use different ones.

TODOs are further directions, also can consider add support for off-cpu analysis.
