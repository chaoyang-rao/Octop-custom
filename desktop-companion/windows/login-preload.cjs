"use strict";
const { contextBridge, ipcRenderer } = require("electron");
// The main process checks the requesting frame's exact engine origin.
void ipcRenderer
  .invoke("login-context")
  .then(async (context) => {
    if (!context || location.origin !== context.origin) return;
    contextBridge.exposeInMainWorld("__DORA_CLIENT__", true);
    if (
      context.token &&
      !localStorage.getItem("auth_token") &&
      !sessionStorage.getItem("auth_token")
    )
      localStorage.setItem("auth_token", context.token);
    let previous = "";
    const check = () => {
      if (location.origin !== context.origin) return;
      const token =
        localStorage.getItem("auth_token") ||
        sessionStorage.getItem("auth_token") ||
        "";
      if (token && token !== previous) {
        previous = token;
        void ipcRenderer.invoke("login-token", token).catch(() => {
          previous = "";
        });
      }
    };
    check();
    setInterval(check, 900);
  })
  .catch(() => {});
