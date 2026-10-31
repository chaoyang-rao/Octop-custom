package com.octop.mobile;

import android.app.Application;

public class OctopApplication extends Application {
    @Override public void onCreate() { super.onCreate(); NativeStrings.initialize(this); }
}
