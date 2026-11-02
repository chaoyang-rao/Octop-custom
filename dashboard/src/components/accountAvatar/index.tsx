import * as React from "react";
import { ProfileAvatar } from "../../pages/Admin/Users/ProfileAvatar";
import { createAccountAvatar } from "./account-avatar.mjs";
import "./account-avatar.css";
export const AccountAvatar = createAccountAvatar({ React, ProfileAvatar });
