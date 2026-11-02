import { request } from "../request";

/** Authenticated project/folder transport injected into the reusable UI factory. */
export const projectFoldersRequest = request;

export interface ThreadProjectContext {
  project_path?: string | null;
  project_name?: string | null;
}
