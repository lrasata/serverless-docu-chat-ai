import axios from "axios";
import { API_BACKEND_URL } from "../../constants/constants";
import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import type { IFile } from "../../types/types.ts";

interface IFileState {
  files: IFile[];
  status: string;
  error: string | null;
}

const initialFileState: IFileState = {
  files: [],
  status: "idle", // 'idle' | 'loading' | 'succeeded' | 'failed' | 'created' | 'updated' | 'deleted'
  error: null,
};

export const fetchFiles = createAsyncThunk(
  "files/fetchFiles",
  async (
    {
      accessToken,
      user_sub,
      resource,
    }: { accessToken: string; user_sub: string; resource: string },
    { rejectWithValue },
  ) => {
    const url = new URL(`${API_BACKEND_URL}/files`);
    url.searchParams.append("id", user_sub);
    url.searchParams.append("resource", resource);

    try {
      const response = await axios.get(url.toString(), {
        headers: {
          Authorization: `Bearer ${accessToken}`,
        },
      });
      const data = response.data.files;
      return { files: data };
    } catch (error) {
      console.error("Error fetching files:", error);
      return rejectWithValue("Oops unable to fetch files from API");
    }
  },
);

const fileSlice = createSlice({
  name: "files",
  initialState: initialFileState,
  reducers: {},
  extraReducers: (builder) => {
    builder.addCase(fetchFiles.pending, (state) => {
      state.status = "loading";
    });
    builder.addCase(fetchFiles.fulfilled, (state, action) => {
      state.status = "succeeded";
      state.files = action.payload.files;
    });
    builder.addCase(fetchFiles.rejected, (state, action) => {
      state.status = "failed";
      state.error = action.error.message || "Something went wrong";
    });
  },
});

export const fileActions = fileSlice.actions;

export default fileSlice.reducer;
