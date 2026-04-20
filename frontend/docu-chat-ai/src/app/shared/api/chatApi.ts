import axios, { type AxiosInstance } from "axios";
import { API_BACKEND_URL } from "../constants/constants.ts";

export interface ConversationTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ChatRequest {
  question: string;
  documentId?: string;
  history?: ConversationTurn[];
}

export interface ChatSource {
  documentId: string;
  chunkId: string;
  relevanceScore: number;
  preview: string;
}

export interface ChatResponse {
  answer: string;
  sources: ChatSource[];
  question: string;
}

export interface ChatError {
  error: string;
  message?: string;
}

class ChatApiService {
  private api: AxiosInstance;

  constructor() {
    this.api = axios.create({
      baseURL: API_BACKEND_URL || "",
      headers: {
        "Content-Type": "application/json",
      },
    });
  }

  private withAuth(token: string) {
    return {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    };
  }

  async sendMessage(
    request: ChatRequest,
    token: string,
  ): Promise<ChatResponse> {
    try {
      const response = await this.api.post<ChatResponse>(
        "/chat",
        request,
        this.withAuth(token),
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response) {
        const errorData = error.response.data as ChatError;
        throw new Error(
          errorData.message || errorData.error || "Failed to send message",
        );
      }
      throw new Error("Network error. Please check your connection.");
    }
  }

  async queryDocument(
    documentId: string,
    question: string,
    token: string,
    history?: ConversationTurn[],
  ): Promise<ChatResponse> {
    return this.sendMessage({ question, documentId, history }, token);
  }

  async queryAllDocuments(
    question: string,
    token: string,
    history?: ConversationTurn[],
  ): Promise<ChatResponse> {
    return this.sendMessage({ question, history }, token);
  }
}

export const chatApi = new ChatApiService();
