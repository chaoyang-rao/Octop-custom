import React from "react";
import { Alert, Input, Modal, Select } from "antd";
import { useTranslation } from "react-i18next";
import { useAgent } from "../../context/AgentContext";
import { message } from "../../utils/antdMessage";
import { octopAgentsApi } from "../../api/modules/octopAgents";
import { createExpertReuseDialogs } from "./dialogs.mjs";

export default createExpertReuseDialogs({
  React,
  Alert,
  Input,
  Modal,
  Select,
  useTranslation,
  useAgent,
  api: octopAgentsApi,
  notify: message,
});
