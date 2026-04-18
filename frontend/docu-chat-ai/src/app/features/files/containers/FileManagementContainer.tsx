import Typography from "@mui/material/Typography";
import FileCardContainer from "./FileCardContainer.tsx";
import { useEffect, useState, useCallback, useRef } from "react";
import { getPresignedUrl } from "../utils/utils.ts";
import { useAuth } from "react-oidc-context";
import LoadingOverlay from "../../../shared/components/LoadingOverlay.tsx";
import { fetchFiles } from "../../../shared/store/redux/FileSlice.ts";
import { useDispatch, useSelector } from "react-redux";
import type {
  AppDispatch,
  RootState,
} from "../../../shared/store/redux/index.ts";
import { Box, LinearProgress, IconButton, Chip } from "@mui/material";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import PictureAsPdfIcon from "@mui/icons-material/PictureAsPdf";
import DescriptionIcon from "@mui/icons-material/Description";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import type { IFile } from "../../../shared/types/types.ts";

interface UploadingFile {
  id: string;
  file: File;
  progress: number;
  status: "uploading" | "done" | "error";
  errorMessage?: string;
  file_key?: string;
}

const formatBytes = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

interface FileManagementContainerProps {
  onSelectionChange?: (selectedIds: string[], pendingIds: string[]) => void;
}

const FileManagementContainer = ({
  onSelectionChange,
}: FileManagementContainerProps) => {
  const [dragging, setDragging] = useState(false);
  const [uploadingFiles, setUploadingFiles] = useState<UploadingFile[]>([]);
  const [awaitingFileKeys, setAwaitingFileKeys] = useState<Set<string>>(
    new Set(),
  );
  const [timedOutFileKeys, setTimedOutFileKeys] = useState<Set<string>>(
    new Set(),
  );
  const pollStartedAtRef = useRef<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const dispatch = useDispatch<AppDispatch>();
  const files: IFile[] = useSelector((state: RootState) => state.files.files);
  const auth = useAuth();

  const loadFiles = useCallback(() => {
    dispatch(
      fetchFiles({
        accessToken: auth.user?.access_token ?? "",
        user_sub: auth.user?.profile.sub ?? "",
        resource: "users",
      }),
    );
  }, [auth.user?.access_token, auth.user?.profile.sub]);

  useEffect(() => {
    loadFiles();
  }, []);

  // Clear awaitingFileKeys once they appear in the store (process_uploaded_file has run)
  useEffect(() => {
    if (awaitingFileKeys.size === 0) return;
    const appearedKeys = [...awaitingFileKeys].filter((k) =>
      files.some((f) => f.file_key === k),
    );
    if (appearedKeys.length > 0) {
      setAwaitingFileKeys((prev) => {
        const next = new Set(prev);
        appearedKeys.forEach((k) => next.delete(k));
        return next;
      });
    }
  }, [files, awaitingFileKeys]);

  // Single poll: runs while a file is awaiting DynamoDB appearance OR still being ingested.
  // Stops after 15 min and marks stuck files as failed.
  useEffect(() => {
    const processingFiles = files.filter(
      (f) => f.status === "processed" && !timedOutFileKeys.has(f.file_key),
    );
    const shouldPoll = awaitingFileKeys.size > 0 || processingFiles.length > 0;

    if (!shouldPoll) {
      pollStartedAtRef.current = null;
      return;
    }

    if (pollStartedAtRef.current === null) {
      pollStartedAtRef.current = Date.now();
    }

    const interval = setInterval(() => {
      if (Date.now() - pollStartedAtRef.current! >= 15 * 60 * 1000) {
        setTimedOutFileKeys(
          (prev) =>
            new Set([...prev, ...processingFiles.map((f) => f.file_key)]),
        );
        pollStartedAtRef.current = null;
        return;
      }
      loadFiles();
    }, 3000);

    return () => clearInterval(interval);
  }, [awaitingFileKeys, files, timedOutFileKeys, loadFiles]);

  const uploadFile = async (file: File, id: string) => {
    if (!auth.isAuthenticated) return;

    const user_sub = auth.user?.profile.sub;
    if (!user_sub) return;

    try {
      const presignedUrlData = await getPresignedUrl(
        user_sub,
        file,
        auth.user?.access_token ?? "",
      );

      if (!presignedUrlData?.upload_url || !presignedUrlData?.file_key) return;

      const { upload_url, file_key } = presignedUrlData;

      setUploadingFiles((prev) =>
        prev.map((f) => (f.id === id ? { ...f, file_key } : f)),
      );

      // Simulate progress while uploading (XHR gives real progress; fetch does not)
      let simulatedProgress = 0;
      const progressInterval = setInterval(() => {
        simulatedProgress = Math.min(
          simulatedProgress + Math.random() * 15 + 5,
          90,
        );
        setUploadingFiles((prev) =>
          prev.map((f) =>
            f.id === id ? { ...f, progress: Math.round(simulatedProgress) } : f,
          ),
        );
      }, 200);

      const response = await fetch(upload_url, {
        method: "PUT",
        body: file,
        headers: { "Content-Type": file.type },
      });

      clearInterval(progressInterval);

      if (!response.ok) {
        throw new Error(`Upload failed: ${response.statusText}`);
      }

      setUploadingFiles((prev) =>
        prev.map((f) =>
          f.id === id ? { ...f, progress: 100, status: "done" } : f,
        ),
      );

      if (file_key) {
        setAwaitingFileKeys((prev) => new Set([...prev, file_key]));
      }
    } catch (error) {
      setUploadingFiles((prev) =>
        prev.map((f) =>
          f.id === id
            ? { ...f, status: "error", errorMessage: (error as Error).message }
            : f,
        ),
      );
      console.error("Upload error:", error);
    }
  };

  const ACCEPTED_EXTENSIONS = new Set([".pdf", ".txt", ".md", ".docx"]);
  const isAccepted = (f: File) =>
    ACCEPTED_EXTENSIONS.has("." + f.name.split(".").pop()?.toLowerCase());

  const handleFiles = useCallback(
    (incoming: FileList | null) => {
      if (!incoming) return;
      const pdfs = Array.from(incoming).filter(isAccepted);

      const newEntries: UploadingFile[] = pdfs.map((file) => ({
        id: crypto.randomUUID(),
        file,
        progress: 0,
        status: "uploading",
      }));

      setUploadingFiles((prev) => [...prev, ...newEntries]);
      newEntries.forEach((entry) => uploadFile(entry.file, entry.id));
    },
    [auth],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles],
  );

  const removeUploadEntry = (id: string) =>
    setUploadingFiles((prev) => prev.filter((f) => f.id !== id));

  return (
    <>
      <Typography variant="h3" mb={2}>
        Upload your documents
      </Typography>

      {/* Drop Zone */}
      <Box
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        sx={{
          border: "1.5px dashed",
          borderColor: dragging ? "primary.main" : "divider",
          borderRadius: 2,
          py: 5,
          px: 3,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 1,
          cursor: "pointer",
          transition: "all 0.2s ease",
          bgcolor: dragging ? "action.hover" : "background.paper",
          "&:hover": {
            borderColor: "primary.main",
            bgcolor: "action.hover",
          },
        }}
      >
        <UploadFileIcon
          sx={{
            fontSize: 36,
            color: dragging ? "primary.main" : "text.secondary",
          }}
        />
        <Typography
          variant="body2"
          color={dragging ? "primary" : "text.secondary"}
        >
          {dragging
            ? "Release to upload"
            : "Drag files here or click to browse"}
        </Typography>
        <Chip
          label=".pdf .txt .md .docx"
          size="small"
          variant="outlined"
          sx={{ fontSize: "0.65rem", height: 20 }}
        />
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.txt,.md,.docx"
          multiple
          style={{ display: "none" }}
          onChange={(e) => handleFiles(e.target.files)}
        />
      </Box>

      {/* Per-file progress list */}
      {uploadingFiles.length > 0 && (
        <Box sx={{ mt: 2, display: "flex", flexDirection: "column", gap: 1 }}>
          {uploadingFiles.map((f) => (
            <Box
              key={f.id}
              sx={{
                display: "flex",
                flexDirection: "column",
                border: "1px solid",
                borderColor:
                  f.status === "done"
                    ? "success.light"
                    : f.status === "error"
                      ? "error.light"
                      : "divider",
                borderRadius: 1,
                px: 2,
                py: 1,
              }}
            >
              <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                {f.file.name.endsWith(".pdf") ? (
                  <PictureAsPdfIcon
                    sx={{ fontSize: 18, color: "text.secondary" }}
                  />
                ) : (
                  <DescriptionIcon
                    sx={{ fontSize: 18, color: "text.secondary" }}
                  />
                )}
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Typography variant="body2" noWrap>
                    {f.file.name}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {formatBytes(f.file.size)}
                  </Typography>
                </Box>
                {f.status === "done" && (
                  <CheckCircleOutlineIcon
                    sx={{ fontSize: 18, color: "success.main" }}
                  />
                )}
                {f.status === "error" && (
                  <ErrorOutlineIcon
                    sx={{ fontSize: 18, color: "error.main" }}
                  />
                )}
                <IconButton
                  size="small"
                  onClick={() => removeUploadEntry(f.id)}
                  sx={{
                    p: 0.5,
                    color: "text.secondary",
                    "&:hover": { color: "error.main" },
                  }}
                >
                  <DeleteOutlineIcon sx={{ fontSize: 16 }} />
                </IconButton>
              </Box>

              {f.status === "uploading" && (
                <LinearProgress
                  variant="determinate"
                  value={f.progress}
                  sx={{ mt: 1, height: 3, borderRadius: 1 }}
                />
              )}
              {f.status === "error" && (
                <Typography variant="caption" color="error" sx={{ mt: 0.5 }}>
                  {f.errorMessage ?? "Upload failed"}
                </Typography>
              )}
            </Box>
          ))}
        </Box>
      )}

      {files.length !== 0 && (
        <Box sx={{ mt: 4 }}>
          <Typography variant="h3" mb={2}>
            Your documents
          </Typography>
          <FileCardContainer
            files={files.map((f) =>
              timedOutFileKeys.has(f.file_key)
                ? { ...f, status: "failed" as const }
                : f,
            )}
            onSelectionChange={onSelectionChange}
          />
        </Box>
      )}

      <LoadingOverlay visible={false} message="Uploading..." />
    </>
  );
};

export default FileManagementContainer;
