
"use client";

import { useState, useEffect, useRef } from 'react';
import type { FC } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
import { ArrowLeft, Send, MessageSquarePlus, Settings2, LogOut, Trash2, PlusCircle, Edit3, BookOpen, PlusSquare } from 'lucide-react';
import {
  SidebarProvider,
  Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarInset,
} from '@/components/ui/sidebar';
import { cn } from '@/lib/utils';
import { ScrollArea } from '@/components/ui/scroll-area'; // Added ScrollArea

interface Message {
  id: string;
  text: string;
  sender: 'user' | 'ai';
  timestamp: Date;
}

interface ChatSession {
  id: string;
  title: string;
  lastActivity: Date;
}

const LearnPage: FC = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState<string>('');
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const scrollViewportRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const initialSessions: ChatSession[] = [
      { id: 'session-1', title: 'Introduction to React', lastActivity: new Date(Date.now() - 3600000 * 2) },
      { id: 'session-2', title: 'State Management', lastActivity: new Date(Date.now() - 3600000 * 5) },
      { id: 'session-3', title: 'Next.js Routing', lastActivity: new Date(Date.now() - 86400000) },
    ];
    setChatSessions(initialSessions.sort((a, b) => b.lastActivity.getTime() - a.lastActivity.getTime()));
    
    if (initialSessions.length > 0) {
      const mostRecentSessionId = initialSessions[0].id;
      setActiveChatId(mostRecentSessionId);
      setMessages([
        { id: 'msg-1', text: 'Hello! How can I learn about this repository?', sender: 'user', timestamp: new Date(Date.now() - 100000) },
        { id: 'msg-2', text: `Hi there! This repository is about ${initialSessions[0].title}. What specifically would you like to know?`, sender: 'ai', timestamp: new Date(Date.now() - 90000) },
      ]);
    } else {
      handleNewChat();
    }
  }, []);

  useEffect(() => {
    if (scrollViewportRef.current) {
      scrollViewportRef.current.scrollTop = scrollViewportRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSendMessage = () => {
    if (inputValue.trim() === '') return;

    const newMessage: Message = {
      id: crypto.randomUUID(),
      text: inputValue,
      sender: 'user',
      timestamp: new Date(),
    };
    setMessages(prevMessages => [...prevMessages, newMessage]);
    const currentInput = inputValue;
    setInputValue('');

    setTimeout(() => {
      const aiResponse: Message = {
        id: crypto.randomUUID(),
        text: `I received your message: "${currentInput}". I am still learning! This is a mock response.`,
        sender: 'ai',
        timestamp: new Date(),
      };
      setMessages(prevMessages => [...prevMessages, aiResponse]);
    }, 1000);

    if (activeChatId) {
      setChatSessions(prevSessions =>
        prevSessions.map(session =>
          session.id === activeChatId ? { ...session, lastActivity: new Date() } : session
        ).sort((a, b) => b.lastActivity.getTime() - a.lastActivity.getTime())
      );
    }
  };

  const handleNewChat = () => {
    const newSessionId = `session-${crypto.randomUUID()}`;
    const newSession: ChatSession = {
      id: newSessionId,
      title: `New Chat ${chatSessions.length + 1}`,
      lastActivity: new Date(),
    };
    setChatSessions(prevSessions => [newSession, ...prevSessions].sort((a, b) => b.lastActivity.getTime() - a.lastActivity.getTime()));
    setActiveChatId(newSessionId);
    setMessages([{ id: 'new-chat-placeholder', text: 'New chat started. Ask me anything!', sender: 'ai', timestamp: new Date() }]);
  };

  const selectChatSession = (sessionId: string) => {
    setActiveChatId(sessionId);
    const selectedSession = chatSessions.find(s => s.id === sessionId);
    setMessages([
      { id: `msg-placeholder-${sessionId}`, text: `Switched to chat: ${selectedSession?.title || 'this chat'}. History would load here.`, sender: 'ai', timestamp: new Date() }
    ]);
     if (activeChatId) {
      setChatSessions(prevSessions =>
        prevSessions.map(session =>
          session.id === activeChatId ? { ...session, lastActivity: new Date() } : session
        ).sort((a, b) => b.lastActivity.getTime() - a.lastActivity.getTime())
      );
    }
  };

  const handleDeleteChat = (sessionId: string, event: React.MouseEvent) => {
    event.stopPropagation();
    setChatSessions(prevSessions => {
      const updatedSessions = prevSessions.filter(session => session.id !== sessionId);
      if (activeChatId === sessionId) {
        if (updatedSessions.length > 0) {
          setActiveChatId(updatedSessions[0].id);
          setMessages([{ id: 'placeholder', text: `Switched to ${updatedSessions[0].title}`, sender: 'ai', timestamp: new Date() }]);
        } else {
          setActiveChatId(null);
          setMessages([]);
        }
      }
      return updatedSessions;
    });
  };
  
  const handleRenameChat = (sessionId: string, event: React.MouseEvent) => {
    event.stopPropagation();
    const currentTitle = chatSessions.find(s => s.id === sessionId)?.title || '';
    const newTitle = prompt("Enter new name for the chat:", currentTitle);
    if (newTitle && newTitle.trim() !== "") {
      setChatSessions(prevSessions =>
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
        <div className="w-[100px]" /> {/* Spacer for centering title */}
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
              <Button variant="outline" className="w-full justify-start h-9" onClick={handleNewChat}>
                <PlusCircle className="mr-2 h-4 w-4" />
                <span className="group-data-[collapsible=icon]:hidden">New Chat</span>
              </Button>
            </SidebarHeader>
            <SidebarContent className="p-2">
              <ScrollArea className="h-full"> {/* ScrollArea for chat sessions list */}
                <SidebarMenu>
                  {chatSessions.map((session) => (
                    <SidebarMenuItem key={session.id} className="group/menu-item relative mb-1">
                      <SidebarMenuButton
                        onClick={() => selectChatSession(session.id)}
                        isActive={activeChatId === session.id}
                        className={cn(
                          "w-full justify-start truncate text-sm h-9",
                          activeChatId === session.id ? "bg-accent text-accent-foreground" : "hover:bg-muted"
                        )}
                        tooltip={{content: session.title, side: 'right', align: 'center', className: "group-data-[collapsible=icon]:flex hidden"}}
                      >
                        <MessageSquarePlus className="h-4 w-4 mr-2 flex-shrink-0"/>
                        <span className="truncate flex-grow group-data-[collapsible=icon]:hidden">{session.title}</span>
                      </SidebarMenuButton>
                      <div className="absolute right-1 top-1/2 -translate-y-1/2 flex opacity-0 group-hover/menu-item:opacity-100 group-data-[collapsible=icon]:hidden transition-opacity">
                        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={(e) => handleRenameChat(session.id, e)}>
                          <Edit3 className="h-3.5 w-3.5"/>
                          <span className="sr-only">Rename</span>
                        </Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={(e) => handleDeleteChat(session.id, e)}>
                          <Trash2 className="h-3.5 w-3.5 text-destructive"/>
                          <span className="sr-only">Delete</span>
                        </Button>
                      </div>
                    </SidebarMenuItem>
                  ))}
                  {chatSessions.length === 0 && (
                    <div className="p-4 text-center text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
                      No chats yet. Start one!
                    </div>
                  )}
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
                {/* <SidebarMenuItem>
                  <Link href="/settings" passHref legacyBehavior>
                    <SidebarMenuButton className="w-full justify-start h-9 text-sm" tooltip={{content: "Settings", side: 'right', align: 'center', className: "group-data-[collapsible=icon]:flex hidden"}}>
                      <Settings2 className="mr-2 h-4 w-4" />
                       <span className="group-data-[collapsible=icon]:hidden">Settings</span>
                    </SidebarMenuButton>
                  </Link>
                </SidebarMenuItem>
                <SidebarMenuItem>
                  <SidebarMenuButton className="w-full justify-start text-destructive hover:text-destructive h-9 text-sm" tooltip={{content: "Logout", side: 'right', align: 'center', className: "group-data-[collapsible=icon]:flex hidden"}}>
                    <LogOut className="mr-2 h-4 w-4" />
                    <span className="group-data-[collapsible=icon]:hidden">Logout</span>
                  </SidebarMenuButton>
                </SidebarMenuItem> */}
              </SidebarMenu>
            </SidebarFooter>
          </Sidebar>

          <SidebarInset className="flex-1 flex flex-col overflow-hidden p-0 md:p-0 md:m-0 md:rounded-none">
            <Card className="h-full flex flex-col shadow-none border-0 md:border-l rounded-none dark:bg-slate-900 dark:border-slate-700">
              <CardHeader className="border-b p-4 dark:border-slate-700">
                <CardTitle className="text-lg">
                  {activeChatId ? chatSessions.find(s => s.id === activeChatId)?.title : "Chat"}
                </CardTitle>
              </CardHeader>

              <ScrollArea className="flex-1" viewportRef={scrollViewportRef}> {/* Use ScrollArea for messages */}
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
                          "p-3 rounded-xl shadow-sm break-words text-sm", // rounded-xl for softer bubbles
                          msg.sender === 'user'
                            ? 'bg-primary text-primary-foreground rounded-br-none'
                            : 'bg-muted text-foreground rounded-bl-none dark:bg-slate-700 dark:text-slate-50' 
                        )}
                      >
                        <p>{msg.text}</p>
                        <p className={cn(
                          "text-xs mt-1.5",
                          msg.sender === 'user' ? 'text-primary-foreground/70 text-right' : 'text-muted-foreground/80 text-left dark:text-slate-400'
                        )}>
                          {msg.timestamp.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
                        </p>
                      </div>
                      {msg.sender === 'user' && (
                        <Avatar className="h-8 w-8 self-start flex-shrink-0">
                           <AvatarImage src="https://placehold.co/40x40.png" alt="User Avatar" data-ai-hint="person silhouette" />
                          <AvatarFallback>U</AvatarFallback>
                        </Avatar>
                      )}
                    </div>
                  ))}
                  {messages.length === 0 && (
                    <div className="text-center text-muted-foreground pt-10">
                      No messages yet. Send a message to start the conversation.
                    </div>
                  )}
                </CardContent>
              </ScrollArea>

              <CardFooter className="p-3 border-t dark:border-slate-700">
                <div className="flex w-full items-start space-x-2"> {/* items-start for better Textarea behavior */}
                  <Textarea
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleSendMessage();
                      }
                    }}
                    placeholder="Type your message..."
                    className="flex-1 min-h-[44px] max-h-[200px] resize-none text-sm p-2.5" 
                    rows={1} // Start with 1 row, auto-expands
                  />
                  <Button onClick={handleSendMessage} disabled={!inputValue.trim()} className="h-[44px] w-[44px]" size="icon">
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

    
