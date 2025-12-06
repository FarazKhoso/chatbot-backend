const express = require('express');
const cors = require('cors');
require('dotenv').config();
const { GoogleGenerativeAI } = require('@google/generative-ai');

const app = express();
const PORT = process.env.PORT || 5001;

app.use(cors());
app.use(express.json());

// Initialize the Gemini API client
const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);

// Get the model
const model = genAI.getGenerativeModel({ model: 'gemini-2.0-flash' });

// Regular chat endpoint
app.post('/api/chat', async (req, res) => {
  try {
    const { message, history = [] } = req.body;

    // For now, we'll just respond to the single message
    // In a real implementation, you'd want to include the conversation history
    const chat = model.startChat({
      history: history.map(item => ({
        role: item.role, // 'user' or 'model'
        parts: [{ text: item.content }]
      })),
      generationConfig: {
        maxOutputTokens: 1000,
      },
    });

    const result = await chat.sendMessage(message);
    const response = await result.response;
    const text = response.text();

    res.json({ response: text });
  } catch (error) {
    console.error('Error with Gemini API:', error);
    res.status(500).json({ error: 'Error communicating with AI service' });
  }
});

// Streaming chat endpoint
app.post('/api/chat-stream', async (req, res) => {
  try {
    const { message, history = [] } = req.body;

    // Set headers for Server-Sent Events (SSE)
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
      'Access-Control-Allow-Origin': '*',
    });

    // For now, we'll just respond to the single message
    // In a real implementation, you'd want to include the conversation history
    const chat = model.startChat({
      history: history.map(item => ({
        role: item.role, // 'user' or 'model'
        parts: [{ text: item.content }]
      })),
      generationConfig: {
        maxOutputTokens: 1000,
      },
    });

    // Create a streaming response
    const result = await chat.sendMessageStream(message);

    for await (const chunk of result.stream) {
      const chunkText = chunk.text();
      // Send the chunk as Server-Sent Event
      res.write(`data: ${JSON.stringify({ text: chunkText })}\n\n`);
    }

    // Send end indicator
    res.write(`data: [DONE]\n\n`);
    res.end();
  } catch (error) {
    console.error('Error with Gemini API streaming:', error);
    res.write(`data: ${JSON.stringify({ error: 'Error communicating with AI service' })}\n\n`);
    res.write(`data: [DONE]\n\n`);
    res.end();
  }
});

app.listen(PORT, () => {
  console.log(`Server is running on port ${PORT}`);
});