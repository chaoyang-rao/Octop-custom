package main

import "octop.desktop/internal/clientupdate"

func compareVersions(left, right string) int { return clientupdate.CompareVersions(left, right) }
