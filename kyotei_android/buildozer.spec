[app]
title = 6艇スタート分析
package.name = kyoteistartanalysis
package.domain = jp.kyotei

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf
source.exclude_dirs = tests, bin, venv

version = 1.0

requirements = python3,kivy,requests,beautifulsoup4,certifi,charset-normalizer,idna,urllib3,soupsieve

orientation = portrait

android.permissions = INTERNET, ACCESS_NETWORK_STATE
android.api = 33
android.minapi = 26
android.ndk = 25b
android.ndk_api = 26
android.archs = arm64-v8a, armeabi-v7a

android.allow_backup = True
android.logcat_filters = *:S python:D

[buildozer]
log_level = 2
warn_on_root = 1
