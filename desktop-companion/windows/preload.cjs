"use strict";
const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld(
  "companionNative",
  Object.freeze({
    platform: process.platform,
    invoke: (op, args = {}) => ipcRenderer.invoke("companion", op, args),
    onEvent: (callback) => {
      const listener = (_event, value) => callback(value);
      ipcRenderer.on("companion-event", listener);
      return () => ipcRenderer.removeListener("companion-event", listener);
    },
  }),
);
