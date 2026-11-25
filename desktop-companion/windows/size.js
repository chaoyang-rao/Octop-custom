"use strict";
const slider = document.querySelector("input"),
  label = document.querySelector("output");
void window.companionNative.invoke("getScale").then((scale) => {
  slider.value = Math.round(scale * 100);
  label.value = slider.value + "%";
});
slider.addEventListener("input", () => {
  label.value = slider.value + "%";
  void window.companionNative.invoke("setScale", {
    scale: Number(slider.value) / 100,
  });
});
