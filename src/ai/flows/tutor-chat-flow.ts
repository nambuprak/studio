
'use server';
/**
 * @fileOverview A Self Tutor chat AI agent.
 *
 * - askTutor - A function that handles the chat interaction with the Self Tutor.
 * - TutorChatInput - The input type for the askTutor function.
 * - TutorChatOutput - The return type for the askTutor function.
 */

import { ai } from '@/ai/genkit';
import { z } from 'genkit';

export const TutorChatInputSchema = z.object({
  tutorId: z.string().describe('The ID of the tutor (repository context) to query.'),
  userQuery: z.string().describe('The user_s question for the tutor.'),
});
export type TutorChatInput = z.infer<typeof TutorChatInputSchema>;

export const TutorChatOutputSchema = z.object({
  aiResponse: z.string().describe('The AI_s response to the user_s query.'),
});
export type TutorChatOutput = z.infer<typeof TutorChatOutputSchema>;


// Define the tool to retrieve context from ChromaDB via the Flask backend
const retrieveContextFromChromaDBTool = ai.defineTool(
  {
    name: 'retrieveContextFromChromaDB',
    description: 'Retrieves relevant context from the knowledge base (ChromaDB) for a given tutor and user query.',
    inputSchema: z.object({
      tutorId: z.string().describe("The ID of the tutor (repository context)."),
      userQuery: z.string().describe("The user's query to find relevant context for."),
    }),
    outputSchema: z.string().describe("The retrieved context as a string, or an empty string if no context is found."),
  },
  async (input) => {
    try {
      // In a real production app, the Flask API URL would come from an environment variable
      const flaskApiUrl = process.env.FLASK_API_URL || 'http://127.0.0.1:5001';
      const response = await fetch(`${flaskApiUrl}/api/query-chroma`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          tutor_id: input.tutorId,
          query_text: input.userQuery,
          n_results: 5, // You can make n_results configurable if needed
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ error: 'Failed to parse error from /api/query-chroma' }));
        console.error(`Error fetching context from ChromaDB: ${response.status} ${response.statusText}`, errorData);
        return `Error retrieving context: ${errorData.error || response.statusText}. Please try again.`;
      }

      const result = await response.json();
      return result.context || ""; // Return empty string if context is null/undefined
    } catch (error: any) {
      console.error('Failed to call /api/query-chroma:', error);
      return `An unexpected error occurred while retrieving context: ${error.message}.`;
    }
  }
);

const tutorSystemPrompt = `You are an intelligent AI assistant for "Self Tutor", designed to help users understand and learn about specific software repositories.
Your primary goal is to answer the user's questions based *solely* on the context provided from the repository's documentation and codebase.

When the user asks a question, you will be given:
1. The user's question.
2. Relevant context retrieved from the vector database (ChromaDB) associated with the specified tutor (repository).

Your task is to:
- Carefully analyze the user's question.
- Thoroughly review the provided context.
- Formulate a clear, concise, and accurate answer to the user's question using *only* the information found in the context.
- If the provided context does not contain enough information to answer the question, or if the question is unrelated to the context, you MUST explicitly state that the information is not available in the provided documents or that you cannot answer based on the given context. Do NOT attempt to answer from general knowledge or make assumptions beyond the provided context.
- If the context is empty, indicate that no relevant information was found for the query.
- Be polite and helpful.
`;

const chatPrompt = ai.definePrompt({
  name: 'tutorChatPrompt',
  system: tutorSystemPrompt,
  input: { schema: TutorChatInputSchema },
  output: { schema: TutorChatOutputSchema },
  tools: [retrieveContextFromChromaDBTool],
  prompt: (input) => `
User Question: "${input.userQuery}"

Use the 'retrieveContextFromChromaDB' tool to fetch relevant information for the tutor ID "${input.tutorId}" based on the user's question.
Then, answer the user's question based *only* on the context returned by the tool.
`,
});


// Define the main flow
const tutorChatFlow = ai.defineFlow(
  {
    name: 'tutorChatFlow',
    inputSchema: TutorChatInputSchema,
    outputSchema: TutorChatOutputSchema,
  },
  async (input) => {
    const { output } = await chatPrompt(input);
    if (!output) {
        return { aiResponse: "I'm sorry, I wasn't able to generate a response. Please try again." };
    }
    return output; // output is already TutorChatOutputSchema compliant
  }
);

export async function askTutor(input: TutorChatInput): Promise<TutorChatOutput> {
  return tutorChatFlow(input);
}
