import React from "react";
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
            <Typography
              variant="body1"
              color={msg.sender === "user" ? "white" : "textPrimary"}
              sx={{ whiteSpace: "pre-wrap" }}
            >
              {msg.text}
            </Typography>

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
                          Document ID: ...{source.documentId.split("/").pop()?.replace(/^[^_]+_/, "")}
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
