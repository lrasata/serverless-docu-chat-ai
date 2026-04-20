import React, { useState } from "react";
import { Box, Alert, CircularProgress, Typography } from "@mui/material";
import ChatWindow from "../components/ChatWindow";
import MessageInput from "../components/MessageInput";
import { chatApi } from "../../../shared/api/chatApi";
import { useAuth } from "react-oidc-context";
import type { Message } from "../../../shared/types/types.ts";

interface ChatPageProps {
  selectedDocumentId?: string;
  isSelectedDocumentPending?: boolean;
}

const ChatPage: React.FC<ChatPageProps> = ({
  selectedDocumentId,
  isSelectedDocumentPending,
}) => {
  const auth = useAuth();
  const [messages, setMessages] = useState<Message[]>([
    {
      id: crypto.randomUUID(),
      sender: "bot",
      text: "Hello! Upload your document and ask me anything about it.",
    },
  ]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const HISTORY_WINDOW = 10;

  const handleSend = async (text: string) => {
    setError(null);

    const history = messages
      .filter((m) => !m.error)
      .slice(-HISTORY_WINDOW)
      .map((m) => ({
        role: (m.sender === "user" ? "user" : "assistant") as "user" | "assistant",
        content: m.text,
      }));

    setMessages((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        sender: "user",
        text,
      },
    ]);
    setIsLoading(true);

    try {
      const token = auth.user?.access_token ?? "";
      const response = selectedDocumentId
        ? await chatApi.queryDocument(selectedDocumentId, text, token, history)
        : await chatApi.queryAllDocuments(text, token, history);

      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          sender: "bot",
          text: response.answer,
          sources: response.sources,
        },
      ]);
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "Failed to get response";
      setError(errorMessage);

      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          sender: "bot",
          text: `Sorry, I encountered an error: ${errorMessage}`,
          error: true,
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {error && (
        <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <ChatWindow messages={messages} />

      {isSelectedDocumentPending && (
        <Alert severity="warning" sx={{ mb: 1 }}>
          A document is still being indexed. Please wait before asking questions
          about it.
        </Alert>
      )}

      {isLoading && (
        <Box sx={{ display: "flex", justifyContent: "center", mb: 2 }}>
          <CircularProgress size={24} />
          <Typography variant="body2" sx={{ ml: 2, color: "text.secondary" }}>
            Thinking...
          </Typography>
        </Box>
      )}

      <MessageInput
        onSend={handleSend}
        disabled={isLoading || !!isSelectedDocumentPending}
      />
    </Box>
  );
};

export default ChatPage;
