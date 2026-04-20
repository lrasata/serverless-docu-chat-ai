import { API_BACKEND_URL } from "../../../shared/constants/constants.ts";

export const getPresignedUrl = async (
  id: number | string,
  file: File,
  accessToken: string,
  resource: string = "users",
): Promise<{ upload_url: string; file_key: string } | undefined> => {
  try {
    const sanitizedName = file.name.replace(/\s+/g, "_");
    const [filenameWithoutExt, extension] = sanitizedName.split(".");

    const mimeType = file.type || "application/octet-stream";

    const queryParams = {
      id: id,
      file_key: filenameWithoutExt,
      ext: extension,
      resource,
      mimeType,
    };

    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(queryParams)) {
      params.append(key, value as string);
    }

    const response = await fetch(`${API_BACKEND_URL}/upload?${params}`, {
      method: "GET",
      headers: { Authorization: `Bearer ${accessToken}` },
    });

    if (!response.ok) {
      throw new Error(`Get presigned url failed: ${response.statusText}`);
    }

    const data = await response.json();

    return {
      upload_url: data["upload_url"],
      file_key: data["file_key"],
    };
  } catch (error) {
    console.error(error);
    return undefined;
  }
};
