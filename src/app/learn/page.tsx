
"use client";

import { useState, useEffect, useRef } from 'react';
import type { FC } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
import { ArrowLeft, Send, MessageSquarePlus, Settings2, LogOut, Trash2, PlusCircle, Edit3, BookOpen, PlusSquare, Loader2 } from 'lucide-react';
import {
  SidebarProvider,
  Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarInset, // Added SidebarInset here
} from '@/components/ui/sidebar';
import { cn } from '@/lib/utils';
import { ScrollArea } from '@/components/ui/scroll-area'; 
import type { TutorChatInput, TutorChatOutput } from '@/ai/flows/tutor-chat-flow'; // Import types

interface Message {
  id: string;
  text: string;
  sender: 'user' | 'ai' | 'system';
  timestamp: Date;
  isLoading?: boolean; // For AI thinking state
}

interface TutorSession { // Renamed from ChatSession
  id: string; // This will be the tutor_id from the database
  title: string; // This will be the project_name
  lastActivity: Date;
  // Add other relevant tutor details if needed, e.g., source_location
}

const generateClientId = () => 'id-' + Date.now().toString(36) + Math.random().toString(36).substring(2);

const LearnPage: FC = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState<string>('');
  const [tutorSessions, setTutorSessions] = useState<TutorSession[]>([]);
  const [activeTutorId, setActiveTutorId] = useState<string | null>(null); // Stores tutor_id
  const scrollViewportRef = useRef<HTMLDivElement>(null);
  const [isFetchingInitialData, setIsFetchingInitialData] = useState(true);


  useEffect(() => {
    async function fetchTutors() {
      setIsFetchingInitialData(true);
      try {
        const response = await fetch('/api/repos');
        if (!response.ok) {
          throw new Error('Failed to fetch tutors');
        }
        const tutorsData: Array<{id: string, project_name: string, status_message?: string, discovered_files_count?: number}> = await response.json();
        
        const formattedSessions: TutorSession[] = tutorsData
          .filter(tutor => {
            const status = tutor.status_message || "";
            // Check for completion messages, including those that mention embedding was skipped
            return status.includes("Embedding process fully completed") || 
                   status.includes("Embedding skipped") ||
                   status.includes("Self Tutor configuration saved. Embedding skipped.");
          })
          .map(tutor => ({
            id: tutor.id,
            title: tutor.project_name,
            lastActivity: new Date(), // Placeholder, ideally load last chat activity
        }));
        
        formattedSessions.sort((a, b) => b.lastActivity.getTime() - a.lastActivity.getTime());
        setTutorSessions(formattedSessions);

        if (formattedSessions.length > 0) {
          const mostRecentSessionId = formattedSessions[0].id;
          setActiveTutorId(mostRecentSessionId);
          setMessages([
            { id: generateClientId(), text: `Switched to tutor: ${formattedSessions[0].title}. Ask me anything about this project!`, sender: 'system', timestamp: new Date() },
          ]);
        } else {
          setMessages([{id: generateClientId(), text: "No tutors available for chat or none have completed processing. Please create a tutor and ensure embedding is complete or skipped.", sender: 'system', timestamp: new Date()}]);
        }
      } catch (error) {
        console.error("Error fetching tutors:", error);
        setMessages([{id: generateClientId(), text: "Error loading tutors. Please try refreshing.", sender: 'system', timestamp: new Date()}]);
      }
      setIsFetchingInitialData(false);
    }
    fetchTutors();
  }, []);


  useEffect(() => {
    if (scrollViewportRef.current) {
      scrollViewportRef.current.scrollTop = scrollViewportRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSendMessage = async () => {
    if (inputValue.trim() === '' || !activeTutorId) return;

    const userMessage: Message = {
      id: generateClientId(),
      text: inputValue,
      sender: 'user',
      timestamp: new Date(),
    };
    setMessages(prevMessages => [...prevMessages, userMessage]);
    
    const currentInput = inputValue;
    setInputValue('');

    const aiThinkingMessageId = generateClientId();
    const aiThinkingMessage: Message = {
      id: aiThinkingMessageId,
      text: "Thinking...",
      sender: 'ai',
      timestamp: new Date(),
      isLoading: true,
    };
    setMessages(prevMessages => [...prevMessages, aiThinkingMessage]);

    try {
      const payload: TutorChatInput = {
        tutorId: activeTutorId,
        userQuery: currentInput,
      };
      // The Genkit Next.js plugin typically exposes flows at /api/flow/<flowName>
      const response = await fetch('/api/flow/tutorChatFlow', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({error: "Failed to parse error from AI response"}));
        throw new Error(errorData.error || `AI service error: ${response.status}`);
      }

      const result: TutorChatOutput = await response.json();
      const aiResponseMessage: Message = {
        id: generateClientId(),
        text: result.aiResponse,
        sender: 'ai',
        timestamp: new Date(),
      };
      setMessages(prevMessages => prevMessages.map(m => m.id === aiThinkingMessageId ? aiResponseMessage : m));

    } catch (error: any) {
      console.error("Error calling Genkit flow:", error);
      const aiErrorMessage: Message = {
        id: generateClientId(),
        text: `Sorry, I encountered an error: ${error.message}`,
        sender: 'ai',
        timestamp: new Date(),
      };
      setMessages(prevMessages => prevMessages.map(m => m.id === aiThinkingMessageId ? aiErrorMessage : m));
    }

    // Update last activity for the current tutor session
    setTutorSessions(prevSessions =>
        prevSessions.map(session =>
          session.id === activeTutorId ? { ...session, lastActivity: new Date() } : session
        ).sort((a, b) => b.lastActivity.getTime() - a.lastActivity.getTime())
      );
  };

  const selectTutorSession = (sessionId: string) => {
    setActiveTutorId(sessionId);
    const selectedSession = tutorSessions.find(s => s.id === sessionId);
    setMessages([
      { id: generateClientId(), text: `Switched to tutor: ${selectedSession?.title || 'this tutor'}. Ask me anything!`, sender: 'system', timestamp: new Date() }
    ]);
     if (activeTutorId) {
      setTutorSessions(prevSessions =>
        prevSessions.map(session =>
          session.id === sessionId ? { ...session, lastActivity: new Date() } : session
        ).sort((a, b) => b.lastActivity.getTime() - a.lastActivity.getTime())
      );
    }
  };

  // handleDeleteChat and handleRenameChat might need to be re-evaluated
  // Deleting a chat session here means deleting the tutor context, which is a bigger operation.
  // Renaming might just be a client-side label or updating the tutor's project_name.
  // For now, these are kept simple or could be removed if they don't fit the "tutor session" model.

  const handleDeleteChat = (sessionId: string, event: React.MouseEvent) => {
    event.stopPropagation();
    alert(`Deletion of tutor context (ID: ${sessionId}) needs backend implementation.`);
    // Implement actual tutor deletion if required, including ChromaDB cleanup and DB record removal.
  };
  
  const handleRenameChat = (sessionId: string, event: React.MouseEvent) => {
    event.stopPropagation();
    const currentTitle = tutorSessions.find(s => s.id === sessionId)?.title || '';
    const newTitle = prompt("Enter new name for the tutor session (this is a local label for now):", currentTitle);
    if (newTitle && newTitle.trim() !== "") {
      setTutorSessions(prevSessions =>
        prevSessions.map(session =>
          session.id === sessionId ? { ...session, title: newTitle.trim(), lastActivity: new Date() } : session
        ).sort((a,b) => b.lastActivity.getTime() - a.lastActivity.getTime())
      );
    }
  };


  return (
    <main className="h-screen flex flex-col bg-background">
      <div className="p-3 border-b flex justify-between items-center dark:bg-slate-900 dark:border-slate-700">
        <Link href="/" passHref legacyBehavior>
          <Button variant="outline" size="sm">
            <ArrowLeft className="mr-2 h-4 w-4" /> Back to Home
          </Button>
        </Link>
        <div className="flex items-center gap-2">
          <BookOpen className="h-6 w-6 text-primary" />
          <h1 className="text-xl font-semibold text-primary">Learn Mode</h1>
        </div>
        <div className="w-[100px]" /> 
      </div>

      <SidebarProvider defaultOpen={true}>
        <div className="flex flex-1 overflow-hidden">
          <Sidebar 
            side="left" 
            variant="sidebar" 
            collapsible="icon" 
            className="bg-card border-r data-[collapsed=true]:bg-background md:data-[collapsed=true]:bg-card dark:bg-slate-800 dark:border-slate-700"
          >
            <SidebarHeader className="p-2">
              {/* "New Chat" button's role is less clear now, maybe it refreshes tutor list or clears current chat?
                 For now, it's disabled if no tutors are available.
                 A better "New Chat" might involve selecting a different tutor not yet in a session.
              */}
               <Button variant="outline" className="w-full justify-start h-9" onClick={() => alert("New Chat functionality to be defined. Select a tutor from the list.")} disabled={tutorSessions.length === 0}>
                <PlusCircle className="mr-2 h-4 w-4" />
                <span className="group-data-[collapsible=icon]:hidden">New Chat</span>
              </Button>
            </SidebarHeader>
            <SidebarContent className="p-2">
              <ScrollArea className="h-full">
                <SidebarMenu>
                  {isFetchingInitialData && <div className="p-4 text-center text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">Loading tutors... <Loader2 className="inline-block ml-1 h-3 w-3 animate-spin"/></div>}
                  {!isFetchingInitialData && tutorSessions.length === 0 && (
                     <div className="p-4 text-center text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
                      No tutors available for chat. Go to "Create Tutor" to set one up.
                    </div>
                  )}
                  {tutorSessions.map((session) => (
                    <SidebarMenuItem key={session.id} className="group/menu-item relative mb-1">
                      <SidebarMenuButton
                        onClick={() => selectTutorSession(session.id)}
                        isActive={activeTutorId === session.id}
                        className={cn(
                          "w-full justify-start truncate text-sm h-9",
                          activeTutorId === session.id ? "bg-accent text-accent-foreground" : "hover:bg-muted"
                        )}
                        tooltip={{content: session.title, side: 'right', align: 'center', className: "group-data-[collapsible=icon]:flex hidden"}}
                      >
                        <MessageSquarePlus className="h-4 w-4 mr-2 flex-shrink-0"/>
                        <span className="truncate flex-grow group-data-[collapsible=icon]:hidden">{session.title}</span>
                      </SidebarMenuButton>
                      {/* Edit/Delete on tutor sessions might require backend changes for persistence */}
                      <div className="absolute right-1 top-1/2 -translate-y-1/2 flex opacity-0 group-hover/menu-item:opacity-100 group-data-[collapsible=icon]:hidden transition-opacity">
                        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={(e) => handleRenameChat(session.id, e)} title="Rename (local label)">
                          <Edit3 className="h-3.5 w-3.5"/>
                          <span className="sr-only">Rename</span>
                        </Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={(e) => handleDeleteChat(session.id, e)} title="Delete Tutor (not implemented)">
                          <Trash2 className="h-3.5 w-3.5 text-destructive"/>
                          <span className="sr-only">Delete</span>
                        </Button>
                      </div>
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </ScrollArea>
            </SidebarContent>
            <SidebarFooter className="mt-auto border-t p-2 dark:border-slate-700">
              <SidebarMenu>
                <SidebarMenuItem>
                  <Link href="/create" passHref legacyBehavior>
                    <SidebarMenuButton className="w-full justify-start h-9 text-sm" tooltip={{content: "Create Self Tutor", side: 'right', align: 'center', className: "group-data-[collapsible=icon]:flex hidden"}}>
                      <PlusSquare className="mr-2 h-4 w-4" />
                      <span className="group-data-[collapsible=icon]:hidden">Create Tutor</span>
                    </SidebarMenuButton>
                  </Link>
                </SidebarMenuItem>
              </SidebarMenu>
            </SidebarFooter>
          </Sidebar>

          <SidebarInset className="flex-1 flex flex-col overflow-hidden p-0 md:p-0 md:m-0 md:rounded-none">
            <Card className="h-full flex flex-col shadow-none border-0 md:border-l rounded-none dark:bg-slate-900 dark:border-slate-700">
              <CardHeader className="border-b p-4 dark:border-slate-700">
                <CardTitle className="text-lg">
                  {activeTutorId ? tutorSessions.find(s => s.id === activeTutorId)?.title : "Select a Tutor"}
                </CardTitle>
              </CardHeader>

              <ScrollArea className="flex-1" viewportRef={scrollViewportRef}>
                <CardContent className="p-4 space-y-4 h-full">
                  {messages.map((msg) => (
                    <div
                      key={msg.id}
                      className={cn(
                        "flex items-end space-x-2 max-w-[85%] md:max-w-[75%]",
                        msg.sender === 'user' ? 'ml-auto justify-end' : 'mr-auto justify-start'
                      )}
                    >
                      {msg.sender === 'ai' && (
                        <Avatar className="h-8 w-8 self-start flex-shrink-0">
                          <AvatarImage src="https://placehold.co/40x40.png" alt="AI Avatar" data-ai-hint="robot face" />
                          <AvatarFallback>AI</AvatarFallback>
                        </Avatar>
                      )}
                      <div
                        className={cn(
                          "p-3 rounded-xl shadow-sm break-words text-sm",
                          msg.sender === 'user'
                            ? 'bg-primary text-primary-foreground rounded-br-none'
                            : msg.sender === 'system' 
                              ? 'bg-accent text-accent-foreground rounded-bl-none w-full max-w-full text-center'
                              : 'bg-muted text-foreground rounded-bl-none dark:bg-slate-700 dark:text-slate-50' 
                        )}
                      >
                        {msg.isLoading ? <Loader2 className="h-5 w-5 animate-spin" /> : <p>{msg.text}</p>}
                        {!msg.isLoading && msg.sender !== 'system' && (
                            <p className={cn(
                            "text-xs mt-1.5",
                            msg.sender === 'user' ? 'text-primary-foreground/70 text-right' : 'text-muted-foreground/80 text-left dark:text-slate-400'
                            )}>
                            {msg.timestamp.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
                            </p>
                        )}
                      </div>
                      {msg.sender === 'user' && (
                        <Avatar className="h-8 w-8 self-start flex-shrink-0">
                           <AvatarImage src="https://placehold.co/40x40.png" alt="User Avatar" data-ai-hint="person human" />
                          <AvatarFallback>U</AvatarFallback>
                        </Avatar>
                      )}
                    </div>
                  ))}
                  {messages.length === 0 && activeTutorId && (
                    <div className="text-center text-muted-foreground pt-10">
                      No messages yet. Send a message to start the conversation with {tutorSessions.find(s=>s.id === activeTutorId)?.title}.
                    </div>
                  )}
                  {!activeTutorId && !isFetchingInitialData && (
                     <div className="text-center text-muted-foreground pt-10">
                      Please select a tutor from the sidebar to start chatting.
                    </div>
                  )}
                </CardContent>
              </ScrollArea>

              <CardFooter className="p-3 border-t dark:border-slate-700">
                <div className="flex w-full items-start space-x-2">
                  <Textarea
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleSendMessage();
                      }
                    }}
                    placeholder={activeTutorId ? "Type your message..." : "Select a tutor to chat"}
                    className="flex-1 min-h-[44px] max-h-[200px] resize-none text-sm p-2.5" 
                    rows={1}
                    disabled={!activeTutorId || isFetchingInitialData}
                  />
                  <Button onClick={handleSendMessage} disabled={!inputValue.trim() || !activeTutorId || isFetchingInitialData} className="h-[44px] w-[44px]" size="icon">
                    <Send className="h-5 w-5" />
                    <span className="sr-only">Send</span>
                  </Button>
                </div>
              </CardFooter>
            </Card>
          </SidebarInset>
        </div>
      </SidebarProvider>
    </main>
  );
}

export default LearnPage;

    