import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Box,
  Typography,
  Paper,
  Chip,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import SourceIcon from "@mui/icons-material/Article";
import type { Message } from "../../../shared/types/types.ts";

interface ChatWindowProps {
  messages: Message[];
}

const ChatWindow: React.FC<ChatWindowProps> = ({ messages }) => {
  return (
    <Box sx={{ flexGrow: 1, overflowY: "auto", mb: 2, p: 1 }}>
      {messages.map((msg) => (
        <Box key={msg.id} sx={{ mb: 2 }}>
          <Paper
            sx={{
              p: 2,
              maxWidth: "80%",
              ml: msg.sender === "user" ? "auto" : 0,
              mr: msg.sender === "bot" ? "auto" : 0,
              bgcolor: msg.error
                ? "error.light"
                : msg.sender === "user"
                  ? "primary.main"
                  : "grey.100",
            }}
          >
            {msg.sender === "user" ? (
              <Typography
                variant="body1"
                color="white"
                sx={{ whiteSpace: "pre-wrap" }}
              >
                {msg.text}
              </Typography>
            ) : (
              <Typography
                variant="body1"
                component="div"
                sx={{
                  "& p": { mt: 0, mb: 1 },
                  "& p:last-child": { mb: 0 },
                  "& ul, & ol": { pl: 2, mb: 1 },
                  "& li": { mb: 0.5 },
                  "& code": { bgcolor: "grey.200", px: 0.5, borderRadius: 0.5 },
                  "& pre": {
                    bgcolor: "grey.200",
                    p: 1,
                    borderRadius: 1,
                    overflowX: "auto",
                  },
                  "& table": { borderCollapse: "collapse", width: "100%", mb: 1 },
                  "& th, & td": { border: "1px solid", borderColor: "divider", px: 1.5, py: 0.75, textAlign: "left" },
                  "& th": { bgcolor: "grey.200", fontWeight: "bold" },
                }}
              >
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown>
              </Typography>
            )}

            {msg.sources && msg.sources.length > 0 && (
              <Box sx={{ mt: 2 }}>
                <Accordion sx={{ bgcolor: "background.paper" }}>
                  <AccordionSummary
                    expandIcon={<ExpandMoreIcon />}
                    aria-controls="sources-content"
                    id="sources-header"
                  >
                    <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                      <SourceIcon fontSize="small" />
                      <Typography variant="body2">
                        Sources ({msg.sources.length})
                      </Typography>
                    </Box>
                  </AccordionSummary>
                  <AccordionDetails>
                    {msg.sources.map((source, idx) => (
                      <Box
                        key={source.chunkId}
                        sx={{
                          p: 1.5,
                          mb: 1,
                          border: 1,
                          borderColor: "divider",
                          borderRadius: 1,
                        }}
                      >
                        <Box
                          sx={{
                            display: "flex",
                            alignItems: "center",
                            gap: 1,
                            mb: 1,
                          }}
                        >
                          <Typography variant="caption" fontWeight="bold">
                            Source {idx + 1}
                          </Typography>
                          <Chip
                            label={`Score: ${(source.relevanceScore * 100).toFixed(0)}%`}
                            size="small"
                            color="primary"
                            variant="outlined"
                          />
                        </Box>
                        <Typography
                          variant="body2"
                          color="text.secondary"
                          sx={{ fontStyle: "italic" }}
                        >
                          {source.preview}
                        </Typography>
                        <Typography
                          variant="caption"
                          color="text.disabled"
                          sx={{ mt: 0.5, display: "block" }}
                        >
                          Document ID: ...
                          {source.documentId
                            .split("/")
                            .pop()
                            ?.replace(/^[^_]+_/, "")}
                        </Typography>
                      </Box>
                    ))}
                  </AccordionDetails>
                </Accordion>
              </Box>
            )}
          </Paper>
        </Box>
      ))}
    </Box>
  );
};

export default ChatWindow;
